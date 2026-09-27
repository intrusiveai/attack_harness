/* Fixed live syscalls; unavailable native-architecture entries are omitted. */
#ifdef SYS_read
    ALLOW(read),
#endif
#ifdef SYS_write
    ALLOW(write),
#endif
#ifdef SYS_readv
    ALLOW(readv),
#endif
#ifdef SYS_writev
    ALLOW(writev),
#endif
#ifdef SYS_pread64
    ALLOW(pread64),
#endif
#ifdef SYS_pwrite64
    ALLOW(pwrite64),
#endif
#ifdef SYS_close
    ALLOW(close),
#endif
#ifdef SYS_close_range
    ALLOW(close_range),
#endif
#ifdef SYS_lseek
    ALLOW(lseek),
#endif
#ifdef SYS_fstat
    ALLOW(fstat),
#endif
#ifdef SYS_newfstatat
    ALLOW(newfstatat),
#endif
#ifdef SYS_stat
    ALLOW(stat),
#endif
#ifdef SYS_lstat
    ALLOW(lstat),
#endif
#ifdef SYS_statx
    ALLOW(statx),
#endif
#ifdef SYS_statfs
    ALLOW(statfs),
#endif
#ifdef SYS_fstatfs
    ALLOW(fstatfs),
#endif
#ifdef SYS_open
    ALLOW(open),
#endif
#ifdef SYS_openat
    ALLOW(openat),
#endif
#ifdef SYS_access
    ALLOW(access),
#endif
#ifdef SYS_faccessat
    ALLOW(faccessat),
#endif
#ifdef SYS_faccessat2
    ALLOW(faccessat2),
#endif
#ifdef SYS_readlink
    ALLOW(readlink),
#endif
#ifdef SYS_readlinkat
    ALLOW(readlinkat),
#endif
#ifdef SYS_getdents64
    ALLOW(getdents64),
#endif
#ifdef SYS_fcntl
    ALLOW(fcntl),
#endif
#ifdef SYS_dup
    ALLOW(dup),
#endif
#ifdef SYS_dup2
    ALLOW(dup2),
#endif
#ifdef SYS_dup3
    ALLOW(dup3),
#endif
#ifdef SYS_poll
    ALLOW(poll),
#endif
#ifdef SYS_ppoll
    ALLOW(ppoll),
#endif
#ifdef SYS_select
    ALLOW(select),
#endif
#ifdef SYS_pselect6
    ALLOW(pselect6),
#endif
#ifdef SYS_epoll_create1
    ALLOW(epoll_create1),
#endif
#ifdef SYS_epoll_ctl
    ALLOW(epoll_ctl),
#endif
#ifdef SYS_epoll_wait
    ALLOW(epoll_wait),
#endif
#ifdef SYS_epoll_pwait
    ALLOW(epoll_pwait),
#endif
#ifdef SYS_munmap
    ALLOW(munmap),
#endif
#ifdef SYS_mremap
    ALLOW(mremap),
#endif
#ifdef SYS_madvise
    ALLOW(madvise),
#endif
#ifdef SYS_brk
    ALLOW(brk),
#endif
#ifdef SYS_futex
    ALLOW(futex),
#endif
#ifdef SYS_rt_sigaction
    ALLOW(rt_sigaction),
#endif
#ifdef SYS_rt_sigprocmask
    ALLOW(rt_sigprocmask),
#endif
#ifdef SYS_rt_sigreturn
    ALLOW(rt_sigreturn),
#endif
#ifdef SYS_rt_sigsuspend
    ALLOW(rt_sigsuspend),
#endif
#ifdef SYS_sigaltstack
    ALLOW(sigaltstack),
#endif
#ifdef SYS_restart_syscall
    ALLOW(restart_syscall),
#endif
#ifdef SYS_getrandom
    ALLOW(getrandom),
#endif
#ifdef SYS_clock_gettime
    ALLOW(clock_gettime),
#endif
#ifdef SYS_clock_getres
    ALLOW(clock_getres),
#endif
#ifdef SYS_clock_nanosleep
    ALLOW(clock_nanosleep),
#endif
#ifdef SYS_nanosleep
    ALLOW(nanosleep),
#endif
#ifdef SYS_gettimeofday
    ALLOW(gettimeofday),
#endif
#ifdef SYS_time
    ALLOW(time),
#endif
#ifdef SYS_times
    ALLOW(times),
#endif
#ifdef SYS_getpid
    ALLOW(getpid),
#endif
#ifdef SYS_getppid
    ALLOW(getppid),
#endif
#ifdef SYS_gettid
    ALLOW(gettid),
#endif
#ifdef SYS_getuid
    ALLOW(getuid),
#endif
#ifdef SYS_geteuid
    ALLOW(geteuid),
#endif
#ifdef SYS_getgid
    ALLOW(getgid),
#endif
#ifdef SYS_getegid
    ALLOW(getegid),
#endif
#ifdef SYS_getgroups
    ALLOW(getgroups),
#endif
#ifdef SYS_uname
    ALLOW(uname),
#endif
#ifdef SYS_sysinfo
    ALLOW(sysinfo),
#endif
#ifdef SYS_getcwd
    ALLOW(getcwd),
#endif
#ifdef SYS_getrlimit
    ALLOW(getrlimit),
#endif
#ifdef SYS_getrusage
    ALLOW(getrusage),
#endif
#ifdef SYS_sched_getaffinity
    ALLOW(sched_getaffinity),
#endif
#ifdef SYS_sched_yield
    ALLOW(sched_yield),
#endif
#ifdef SYS_exit
    ALLOW(exit),
#endif
#ifdef SYS_exit_group
    ALLOW(exit_group),
#endif
#ifdef SYS_mkdir
    ALLOW(mkdir),
#endif
#ifdef SYS_mkdirat
    ALLOW(mkdirat),
#endif
#ifdef SYS_unlink
    ALLOW(unlink),
#endif
#ifdef SYS_unlinkat
    ALLOW(unlinkat),
#endif
#ifdef SYS_rename
    ALLOW(rename),
#endif
#ifdef SYS_renameat
    ALLOW(renameat),
#endif
#ifdef SYS_renameat2
    ALLOW(renameat2),
#endif
#ifdef SYS_ftruncate
    ALLOW(ftruncate),
#endif
#ifdef SYS_truncate
    ALLOW(truncate),
#endif
#ifdef SYS_fsync
    ALLOW(fsync),
#endif
#ifdef SYS_fdatasync
    ALLOW(fdatasync),
#endif
#ifdef SYS_fchmod
    ALLOW(fchmod),
#endif
#ifdef SYS_chmod
    ALLOW(chmod),
#endif
#ifdef SYS_fchmodat
    ALLOW(fchmodat),
#endif
#ifdef SYS_utimensat
    ALLOW(utimensat),
#endif
