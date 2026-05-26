# False Positive Prevention Guide (Condensed)

## Core Principles
Before reporting any issue:
1. **Trace concrete execution path** - Show bug is reachable
2. **Check existing protections** - Verify no guards prevent bug
3. **Verify actual impact** - Prove real consequence exists
4. **Context matters** - Understand surrounding code

## Common False Positive Patterns

### NULL Pointer Dereference
**Verify:**
- NULL check doesn't exist earlier in function
- Pointer can actually be NULL at dereference point
- Reading a pointer field (`foo->bar`) is NOT dereferencing `bar`

**False positive if:**
- Earlier `if (foo)` check exists
- Function contract guarantees non-NULL
- Called only from paths that check NULL

### Use-After-Free
**Verify:**
- Free actually happens before use
- No refcount prevents premature free
- Pointer not reassigned between free and use

**False positive if:**
- Free is conditional and use is in else branch
- Refcount prevents free while object in use
- Code paths are mutually exclusive

### Resource Leak
**Verify:**
- All paths to function exit checked
- Early returns don't bypass cleanup
- Error handling paths leak resource

**False positive if:**
- Caller owns cleanup responsibility
- Ownership transferred to another structure
- Cleanup happens in destructor/callback

### Race Condition
**Verify:**
- Concurrent access is actually possible
- No lock protects the access
- Lock ordering is violated

**False positive if:**
- Access is serialized by design
- Lock held but not obvious from snippet
- Single-threaded context (init, shutdown)

### Locking Issues
**Verify:**
- Lock actually needed for data protection
- Lock not held in execution path
- Lock order violation creates deadlock

**False positive if:**
- Access happens during init/shutdown (no concurrency)
- Function contract requires lock held by caller
- Read-only access to immutable data

## Verification Checklist
- [ ] Bug reachable in practice?
- [ ] Existing checks don't prevent it?
- [ ] Real impact (crash, leak, corruption)?
- [ ] Not a false alarm from partial context?
- [ ] Function contracts verified?
- [ ] Caller context checked?

## Red Flags for False Positives
- Analysis based only on diff fragment (not full function)
- Assumptions about function behavior without verification
- Ignoring conditional guards or config dependencies
- Missing caller context
- Theoretical bug with no concrete path
