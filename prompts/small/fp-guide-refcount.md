# False Positive Prevention Guide - Reference Counting & UAF

## 5. Reference Counting and Use-After-Free

### 5a. Reference Counter Analysis

**Before reporting a UAF in code with reference counting:**

**CRITICAL: Verify the reference counting model:**
1. Find the initial value of the reference counter
   - Output: "ref_ctr initialized to X at line Y"
2. Find ALL increment operations
   - Output: list each increment with location and condition
3. Find ALL decrement operations
   - Output: list each decrement with location
4. Trace reference count through the problematic path
   - Output: step-by-step count showing when it can reach 0

**Common FALSE POSITIVE pattern:**
- Assuming reference counter starts at 1
- Not counting all increments (multiple waiters/users)
- Not recognizing that counter > 1 prevents premature free

### 5b. Use-After-Free Confusion
**Distinguish between**:
- Use-after-free (accessing freed memory) <- Report this
- Use-before-free (using then freeing) <- Don't report
- Free-after-use (normal cleanup) <- Don't report
