"""Directional nonblocking guest FIFO transport; no dummy endpoints or reconnect."""
from collections import deque
import errno
import fcntl
import os
import stat
import time

from operator_contracts import ContractError
from operator_contracts.startup import require

LANES=("ordinary-in","ordinary-out","control-in","control-out")
TRANSFER_SECONDS=5
POLL_SECONDS=.001


class FIFO:
    def __init__(self,protocol,root="/run/operator/ipc",*,clock=time.monotonic):
        self.protocol,self.clock=protocol,clock
        self.root=-1;self.fds={};self.identities={};self.closed=False;self.pinned=False
        self.state=None;self.start_deadline=clock()+60
        self.queues={lane:deque() for lane in LANES};self.next={lane:0 for lane in LANES}
        self.decoders={lane:protocol.new_frame_decoder(lane) for lane in ("ordinary-in","control-in")}
        self.headers={lane:bytearray() for lane in self.decoders}
        self.remaining={lane:0 for lane in self.decoders};self.read_deadline={};self.full={}
        try:
            self.root=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
            with os.scandir(self.root) as names:
                found=[]
                for entry in names:
                    require(len(found)<4);found.append(entry.name)
                require(set(found)==set(LANES))
            for lane in LANES:
                info=os.stat(lane,dir_fd=self.root,follow_symlinks=False)
                require(stat.S_ISFIFO(info.st_mode) and info.st_nlink==1)
                self.identities[lane]=(info.st_dev,info.st_ino)
                if lane.endswith("in"):self._open(lane)
        except (OSError,ContractError):
            self.close();raise ContractError("FIFO initialization failed") from None

    @staticmethod
    def capacity(lane):return 16 if lane.startswith("control") else 2

    def _open(self,lane):
        mode=os.O_RDONLY if lane.endswith("in") else os.O_WRONLY
        fd=os.open(lane,mode|os.O_NONBLOCK|os.O_NOFOLLOW,dir_fd=self.root)
        self.fds[lane]=fd
        info=os.fstat(fd)
        require(stat.S_ISFIFO(info.st_mode) and (info.st_dev,info.st_ino)==self.identities[lane])

    def close(self):
        self.closed=True
        if self.state is not None:self.state.close()
        for fd in self.fds.values():os.close(fd)
        self.fds.clear()
        if self.root>=0:os.close(self.root);self.root=-1

    def pin_descriptors(self):
        """Bootstrap-only: reserve guest endpoints at FD 3..6 before live policy.

        The composition root must have closed unrelated inherited descriptors.
        Call only in the disposable guest, never in a host application's process.
        """
        require(not self.closed and not self.pinned and len(self.fds)==4)
        copies={};root=-1
        try:
            root=fcntl.fcntl(self.root,fcntl.F_DUPFD_CLOEXEC,7)
            for lane in LANES:copies[lane]=fcntl.fcntl(self.fds[lane],fcntl.F_DUPFD_CLOEXEC,7)
            os.close(self.root);self.root=root;root=-1
            for fd in self.fds.values():os.close(fd)
            self.fds.clear()
            for index,lane in enumerate(LANES,3):
                os.dup2(copies[lane],index,inheritable=False)
                self.fds[lane]=index
            self.pinned=True
        except OSError:
            self.close();raise ContractError("FIFO descriptor handoff failed") from None
        finally:
            for fd in copies.values():os.close(fd)
            if root>=0:os.close(root)

    def _check(self):
        require(not self.closed)
        if self.state is None:require(self.clock()<self.start_deadline)
        with os.scandir(self.root) as names:
            found=[]
            for entry in names:
                require(len(found)<4);found.append(entry.name)
            require(set(found)==set(LANES))
        for lane,identity in self.identities.items():
            info=os.stat(lane,dir_fd=self.root,follow_symlinks=False)
            require(stat.S_ISFIFO(info.st_mode) and info.st_nlink==1 and (info.st_dev,info.st_ino)==identity)
        for deadline in (*self.read_deadline.values(),*self.full.values()):require(self.clock()<deadline)
        for lane in ("ordinary-out","control-out"):
            if self.queues[lane]:require(self.clock()<self.queues[lane][0][1])

    def send(self,lane,raw):
        try:
            self._check();require(lane in ("ordinary-out","control-out") and self.state is not None)
            frame=self.protocol.encode_frame(lane,raw)
            message=self.protocol.validate_lane_message(lane,raw)
            require(message["seq"]==self.next[lane] and message["campaign_id"]==self.campaign and message["launch_id"]==self.launch)
            require(len(self.queues[lane])<self.capacity(lane))
            self.queues[lane].append([frame,self.clock()+TRANSFER_SECONDS,0,raw])
            self.next[lane]+=1
        except (OSError,ContractError):
            self.close();raise ContractError("FIFO send failed") from None

    def take(self,lane):
        require(not self.closed and lane in self.decoders)
        if lane in self.full and self.clock()>=self.full[lane]:
            self.close();raise ContractError("FIFO consumer deadline expired")
        if not self.queues[lane]:return None
        self.full.pop(lane,None)
        return self.queues[lane].popleft()

    def pump(self):
        try:
            self._check()
            for lane in ("ordinary-out","control-out"):
                if lane not in self.fds:
                    try:self._open(lane)
                    except OSError as e:
                        if e.errno!=errno.ENXIO or self.state is not None:raise
            self._receive("control-in")
            self._send("control-out")
            self._receive("ordinary-in")
            self._send("ordinary-out")
        except (OSError,ContractError):
            self.close();raise ContractError("FIFO transport failed") from None

    def _receive(self,lane):
        if len(self.queues[lane])==self.capacity(lane):
            self.full.setdefault(lane,self.clock()+TRANSFER_SECONDS);return
        header=self.headers[lane]
        for _ in range(4):
            count=4-len(header) if len(header)<4 else min(65536,self.remaining[lane])
            try:chunk=os.read(self.fds[lane],count)
            except (BlockingIOError,InterruptedError):return
            if not chunk:
                require(self.state is None and lane not in self.read_deadline);return
            self.read_deadline.setdefault(lane,self.clock()+TRANSFER_SECONDS)
            consumed,raw=self.decoders[lane].feed(chunk)
            require(consumed==len(chunk))
            if len(header)<4:
                header.extend(chunk)
                if len(header)==4:self.remaining[lane]=int.from_bytes(header,"big")
            else:self.remaining[lane]-=len(chunk)
            if raw is not None:
                require(self.clock()<self.read_deadline[lane])
                message=self.protocol.validate_lane_message(lane,raw)
                if self.state is None:
                    require(lane=="control-in" and message["kind"]=="bootstrap" and message["seq"]==0 and len(self.fds)==4)
                    self.campaign,self.launch=message["campaign_id"],message["launch_id"]
                    self.state=self.protocol.new_transport_state("guest",self.campaign,self.launch)
                self.state.accept(lane,raw)
                self.queues[lane].append(raw);header.clear();self.remaining[lane]=0
                del self.read_deadline[lane]
                return

    def _send(self,lane):
        if lane not in self.fds or not self.queues[lane]:return
        item=self.queues[lane][0];frame,deadline,written,raw=item
        require(self.clock()<deadline)
        try:count=os.write(self.fds[lane],memoryview(frame)[written:written+65536])
        except (BlockingIOError,InterruptedError):return
        require(count>0 and self.clock()<deadline)
        item[2]+=count
        if item[2]==len(frame):
            self.state.record_published(lane,raw);self.queues[lane].popleft()
