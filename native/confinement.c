/* Release-owned Linux confinement. CPython stable ABI 3.12+, one native thread. */
#define Py_LIMITED_API 0x030c0000
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <dirent.h>
#include <errno.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#if defined(__x86_64__)
#define NATIVE_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__)
#define NATIVE_ARCH AUDIT_ARCH_AARCH64
#else
#error Unsupported confinement architecture
#endif

#define DENIED (SECCOMP_RET_ERRNO | EPERM)
#define ALLOW(name) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_##name, 0, 1), BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW)
#define NO_EXEC_MEMORY(name) \
    BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_##name, 0, 4), \
    BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data,args[2])), \
    BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K, PROT_EXEC, 0, 1), \
    BPF_STMT(BPF_RET|BPF_K, DENIED), \
    BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW)

static const struct sock_filter policy[] = {
    BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data,arch)),
    BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, NATIVE_ARCH, 1, 0),
    BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
    BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data,nr)),
#if defined(__x86_64__)
    /* x32 shares the x86_64 audit value; reject its alternate syscall numbers. */
    BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K, 0x40000000U, 0, 1),
    BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
#endif
    NO_EXEC_MEMORY(mmap),
    NO_EXEC_MEMORY(mprotect),
    /* Remaining calls are emitted from the reviewed source-owned allowlist. */
#include "live_allowlist.h"
    BPF_STMT(BPF_RET|BPF_K, DENIED)
};

static int installed = 0;

static int single_thread(void) {
    DIR *directory = opendir("/proc/self/task");
    if (directory == NULL) return 0;
    int count = 0, valid = 1;
    struct dirent *entry;
    errno = 0;
    while ((entry = readdir(directory)) != NULL) {
        if (entry->d_name[0] == '.') continue;
        if (++count > 1) break;
    }
    if (errno != 0) valid = 0;
    if (closedir(directory) != 0) valid = 0;
    return valid && count == 1;
}

static PyObject *install_filter(PyObject *self, PyObject *unused) {
    (void)self; (void)unused;
    if (installed || geteuid() == 0 || !single_thread() ||
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) {
        PyErr_SetString(PyExc_RuntimeError, "confinement prerequisites failed");
        return NULL;
    }
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(policy) / sizeof(policy[0])),
        .filter = (struct sock_filter *)policy
    };
    /* TSYNC positive return values are failures too, not successful installs. */
    long result = syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                          SECCOMP_FILTER_FLAG_TSYNC, &program);
    if (result != 0) {
        PyErr_SetString(PyExc_RuntimeError, "live confinement installation failed");
        return NULL;
    }
    installed = 1;
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"install", install_filter, METH_NOARGS, "Install the irreversible release allowlist once."},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_confinement", "Linux live confinement", -1, methods,
    NULL, NULL, NULL, NULL
};
PyMODINIT_FUNC PyInit__confinement(void) { return PyModule_Create(&module); }
