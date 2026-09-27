"""Bounded descriptor-relative reads of immutable release and campaign data."""

import os
import stat

from operator_contracts import ContractError
from operator_contracts.canonical import raw_digest
from operator_contracts.startup import inventory_paths, require


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _safe(info, directory, readonly):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    return (kind(info.st_mode) and not info.st_mode & 0o7022
            and (not readonly or not info.st_mode & 0o222)
            and (directory or info.st_nlink == 1))


class Directory:
    """Paths come from validated manifests, never directly from model arguments.

    Ancestors of the selected fixed mount are trusted launcher paths. The mount
    itself and every path underneath are opened without following symlinks.
    ``tick`` services control and checks deadlines between bounded read chunks.
    """

    def __init__(self, path, *, readonly=True, tick=lambda: None):
        self._fd = -1
        self.readonly, self.tick = readonly, tick
        try:
            before = os.stat(path, follow_symlinks=False)
            require(_safe(before, True, readonly))
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK)
            self._fd = fd
            require(_identity(before) == _identity(os.fstat(fd)))
        except (OSError, ContractError):
            self.close()
            raise ContractError("invalid immutable directory") from None

    def close(self):
        if self._fd >= 0:
            os.close(self._fd)
            self._fd = -1

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _components(self, path):
        require(type(path) is str)
        inventory_paths([{"path": path}])
        require(self._fd >= 0)
        return path.split("/")

    def read(self, path, maximum, *, size=None, digest=None):
        require(type(maximum) is int and 0 <= maximum <= 128 << 20)
        parts = self._components(path)
        parent = os.dup(self._fd)
        opened = []
        try:
            for name in parts[:-1]:
                self.tick()
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                require(_safe(before, True, self.readonly))
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                opened.append((parent, name, before))
                parent = child
                require(_identity(before) == _identity(os.fstat(parent)))
            self.tick()
            name = parts[-1]
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require(_safe(before, False, self.readonly) and before.st_size <= maximum)
            require(size is None or before.st_size == size)
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            try:
                require(_identity(before) == _identity(os.fstat(fd)))
                chunks, total = [], 0
                while True:
                    self.tick()
                    chunk = os.read(fd, min(65536, maximum + 1 - total))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    total += len(chunk)
                    require(total <= maximum)
                raw = b"".join(chunks)
                require(total == before.st_size and _identity(before) == _identity(os.fstat(fd)))
                require(_identity(before) == _identity(os.stat(name, dir_fd=parent, follow_symlinks=False)))
            finally:
                os.close(fd)
            for ancestor, name, before in opened:
                require(_identity(before) == _identity(os.stat(name, dir_fd=ancestor, follow_symlinks=False)))
            require(digest is None or raw_digest(raw) == digest)
            return raw
        except OSError:
            raise ContractError("immutable file unavailable") from None
        finally:
            os.close(parent)
            for ancestor, _, _ in opened:
                os.close(ancestor)

    def inventory(self, entries, *, maximum_files=4096, maximum_bytes=128 << 20):
        """Verify exact names/types, then read only declared bounded content."""
        require(type(entries) is list and len(entries) <= maximum_files)
        inventory_paths(entries)
        files, directories = set(), {""}
        total = 0
        for entry in entries:
            require(type(entry["size_bytes"]) is int and entry["size_bytes"] >= 0)
            total += entry["size_bytes"]
            require(total <= maximum_bytes)
            files.add(entry["path"])
            parts = entry["path"].split("/")
            directories.update("/".join(parts[:n]) for n in range(1, len(parts)))
        seen = set()

        def walk(fd, prefix):
            self.tick()
            before = os.fstat(fd)
            with os.scandir(fd) as names:
                for entry in names:
                    self.tick()
                    path = prefix + entry.name
                    require(path in files or path in directories)
                    require(path not in seen)
                    seen.add(path)
                    info = entry.stat(follow_symlinks=False)
                    if path in directories:
                        require(_safe(info, True, self.readonly))
                        child = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                        try:
                            require(_identity(info) == _identity(os.fstat(child)))
                            walk(child, path + "/")
                            require(_identity(info) == _identity(os.stat(entry.name, dir_fd=fd, follow_symlinks=False)))
                        finally:
                            os.close(child)
                    else:
                        require(_safe(info, False, self.readonly))
            require(_identity(before) == _identity(os.fstat(fd)))

        try:
            walk(self._fd, "")
            require(seen == files | (directories - {""}))
            return {entry["path"]: self.read(entry["path"], entry["size_bytes"],
                    size=entry["size_bytes"], digest=entry["digest"]) for entry in entries}
        except OSError:
            raise ContractError("immutable inventory unavailable") from None
