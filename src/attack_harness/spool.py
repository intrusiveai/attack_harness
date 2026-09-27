"""Single-threaded guest side of Operator's atomic-file transport."""

from collections import deque
import os
import stat
import time

from operator_contracts import ContractError
from operator_contracts.canonical import raw_digest
from operator_contracts.startup import require
from operator_contracts.transport import lane_info, parse_spool_message_name, spool_message_name

LANES = ("ordinary-in", "ordinary-out", "control-in", "control-out")
POLL_SECONDS = .01
TRANSFER_SECONDS = 5


def _regular(s, maximum):
    require(stat.S_ISREG(s.st_mode) and s.st_nlink <= 1 and s.st_size <= maximum)


def _read(fd, name, maximum):
    # Open first: an ACK can legitimately be atomically replaced concurrently.
    source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    try:
        before = os.fstat(source)
        _regular(before, maximum)
        chunks, total = [], 0
        while True:
            part = os.read(source, min(65536, maximum + 1 - total))
            if not part:break
            chunks.append(part)
            total += len(part)
            require(total <= maximum)
        after = os.fstat(source)
        _regular(after, maximum)
        require(before.st_size == after.st_size == total and before.st_mtime_ns == after.st_mtime_ns)
        return b"".join(chunks)
    finally:
        os.close(source)


def _publish(fd, temp, name, raw, *, replace=False):
    if not replace:
        try:os.stat(name,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError:pass
        else:raise ContractError("spool publication already exists")
    target = os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
    try:
        os.fchmod(target,0o640)
        written=0
        while written<len(raw):
            count=os.write(target,memoryview(raw)[written:])
            require(count>0)
            written+=count
    finally:os.close(target)
    # Each lane has exactly one producer; the opposite side is mounted read-only.
    os.rename(temp,name,src_dir_fd=fd,dst_dir_fd=fd)


class Spool:
    """Owns fresh lanes and bounded queues; never reconnects or resumes.

    ``pump`` must run during all ordinary waits. It admits control before ordinary
    traffic. ``take`` returns copied validated bytes; ACKs already account for
    capture and do not wait for application-level completion.
    """

    def __init__(self, protocol, root="/run/operator/spool", *, clock=time.monotonic):
        self.protocol,self.clock=protocol,clock
        self.fds={};self.identities={};self.root=-1;self.closed=False
        self.state=None
        self.queues={lane:deque() for lane in LANES}
        self.next={lane:0 for lane in LANES}
        self.known={lane:{} for lane in ("ordinary-in","control-in")}
        self.temporary={lane:{} for lane in self.known}
        self.full={};self.outstanding={lane:deque() for lane in ("ordinary-out","control-out")}
        self.ack_dirty=False
        try:
            self.root=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
            for lane in LANES:
                fd=os.open(lane,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=self.root)
                self.fds[lane]=fd
                s=os.fstat(fd);self.identities[lane]=(s.st_dev,s.st_ino)
                if lane.endswith("out"):
                    with os.scandir(fd) as names:require(next(names,None) is None)
        except (OSError,ContractError):
            self.close();raise ContractError("spool initialization failed") from None

    @staticmethod
    def capacity(lane):return 16 if lane.startswith("control") else 2

    def close(self):
        self.closed=True
        if self.state is not None:self.state.close()
        for fd in self.fds.values():os.close(fd)
        self.fds.clear()
        if self.root>=0:os.close(self.root);self.root=-1

    def _check(self):
        require(not self.closed)
        for lane,identity in self.identities.items():
            s=os.stat(lane,dir_fd=self.root,follow_symlinks=False)
            require(stat.S_ISDIR(s.st_mode) and (s.st_dev,s.st_ino)==identity)

    def send(self,lane,raw):
        try:
            self._check()
            require(lane in self.outstanding and type(raw) is bytes and self.state is not None)
            message=self.protocol.validate_lane_message(lane,raw)
            require(message["seq"]==self.next[lane])
            require(message["campaign_id"]==self.campaign and message["launch_id"]==self.launch)
            require(len(self.queues[lane])<self.capacity(lane))
            self.queues[lane].append((raw,self.clock()+TRANSFER_SECONDS))
            self.next[lane]+=1
        except (OSError,ContractError):
            self.close();raise ContractError("spool send failed") from None

    def take(self,lane):
        require(not self.closed and lane in self.known)
        if lane in self.full and self.clock()>=self.full[lane]:
            self.close();raise ContractError("spool consumer deadline expired")
        if not self.queues[lane]:return None
        self.full.pop(lane,None)
        return self.queues[lane].popleft()

    def pump(self):
        try:
            self._check()
            now=self.clock()
            for lane,queue in self.outstanding.items():
                require(not queue or now<queue[0][1])
                pending=self.queues[lane]
                require(not pending or now<pending[0][1])
            if self.state is not None:
                try:raw=_read(self.fds["control-in"],"consumed.json",1024)
                except FileNotFoundError:pass
                else:self.state.apply_ack(raw)
                positions=self.state.acknowledged()
                for lane,queue in self.outstanding.items():
                    position=positions["control_seq" if lane.startswith("control") else "ordinary_seq"]
                    while queue and position is not None and queue[0][0]<=position:
                        os.unlink(spool_message_name(queue[0][0]),dir_fd=self.fds[lane]);queue.popleft()
            self._receive("control-in")
            self._ack()
            self._send("control-out")
            self._receive("ordinary-in")
            self._ack()
            self._send("ordinary-out")
            for deadline in self.full.values():require(self.clock()<deadline)
        except (OSError,ContractError):
            self.close();raise ContractError("spool transport failed") from None

    def _ack(self):
        if self.ack_dirty:
            deadline=self.clock()+TRANSFER_SECONDS
            _publish(self.fds["control-out"],".consumed.tmp","consumed.json",self.state.ack_bytes(),replace=True)
            require(self.clock()<deadline);self.ack_dirty=False

    def _send(self,lane):
        queue=self.queues[lane]
        if not queue or len(self.outstanding[lane])>=self.capacity(lane):return
        raw,deadline=queue[0]
        require(self.clock()<deadline)
        message=self.protocol.validate_lane_message(lane,raw);seq=message["seq"]
        _publish(self.fds[lane],spool_message_name(seq,True),spool_message_name(seq),raw)
        require(self.clock()<deadline)
        self.state.record_published(lane,raw)
        queue.popleft();self.outstanding[lane].append((seq,self.clock()+TRANSFER_SECONDS))

    def _receive(self,lane):
        now=self.clock();fd=self.fds[lane];maximum=lane_info(lane)[2]
        require(all(now<deadline for deadline in self.temporary[lane].values()))
        ready={};temporary=set();count=0;total=0
        with os.scandir(fd) as names:
            for index,entry in enumerate(names):
                require(index<self.capacity(lane)+3)
                try:info=entry.stat(follow_symlinks=False)
                except FileNotFoundError:continue
                _regular(info,maximum)
                name=entry.name
                if lane=="control-in" and name in ("consumed.json",".consumed.tmp"):
                    require(info.st_size<=1024)
                    if name.startswith("."):temporary.add(name)
                    continue
                seq,temp=parse_spool_message_name(name)
                count+=1;total+=info.st_size
                if temp:
                    require(seq>=self.next[lane]);temporary.add(name)
                else:ready[seq]=name
        require(count<=self.capacity(lane) and total<=self.capacity(lane)*maximum and len(temporary)<=1)
        self.temporary[lane]={name:self.temporary[lane].get(name,now+TRANSFER_SECONDS) for name in temporary}
        for seq,(digest,consumed) in list(self.known[lane].items()):
            if seq not in ready:
                require(consumed);del self.known[lane][seq]
        for seq,name in sorted(ready.items()):
            known=self.known[lane].get(seq)
            require(seq>=self.next[lane] or known is not None)
            try:raw=_read(fd,name,maximum)
            except FileNotFoundError:
                require(known is not None and known[1]);del self.known[lane][seq];continue
            digest=raw_digest(raw)
            require(known is None or digest==known[0])
            message=self.protocol.validate_spool_message(lane,name,raw)
            if seq<self.next[lane]:continue
            require(all(n in ready for n in range(self.next[lane],seq)))
            self.known[lane][seq]=(digest,False)
            if len(self.queues[lane])==self.capacity(lane):
                self.full.setdefault(lane,now+TRANSFER_SECONDS);continue
            require(seq==self.next[lane])
            if self.state is None:
                require(lane=="control-in" and message["kind"]=="bootstrap" and seq==0)
                self.campaign,self.launch=message["campaign_id"],message["launch_id"]
                self.state=self.protocol.new_transport_state("guest",self.campaign,self.launch)
            self.state.accept(lane,raw)
            self.next[lane]+=1;self.queues[lane].append(raw)
            self.known[lane][seq]=(digest,True);self.ack_dirty=True
