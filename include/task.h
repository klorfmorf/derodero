#ifndef TASK_H
#define TASK_H

#include <ultra64.h>

typedef struct task Task;

typedef s32 (*task_proc_t)(Task *self, s16 message, s32 value);

struct task {
    u16         flags;
    u8          works;
    const char *name;
    Task       *parent;
    Task       *child;
    Task       *prev;
    Task       *next;
    s32         overlay;
    task_proc_t proc;
    u8          work[0x60];
};

s32 task_default_proc(Task *self, s16 message, s32 value);
s32 task_root_proc(Task *self, s16 message, s32 value);
void task_reset(Task *task);
void task_init(void);
Task *task_alloc(s32 works);
Task *task_alloc_root(task_proc_t proc);
Task *task_create(Task *parent, task_proc_t proc, s32 overlay, s32 value);
Task *task_create_ext(Task *parent, task_proc_t proc, s32 works, s32 overlay, s32 value);
void task_free(Task *task);
s32 task_broadcast(Task *task, s16 message, s32 value);
s32 task_dispatch(Task *task, s16 message, s32 value);
void task_detach(Task *task);
void task_attach(Task *task, Task *parent);
Task *task_destroy(Task *task);
void task_destroy_children(Task *parent);
s32 task_child_count(Task *task);
Task *task_find(Task *root, task_proc_t proc, s32 overlay);
const char *task_get_name(Task *task);
s32 task_stub(void);

#endif // TASK_H
