# False Positive Prevention Guide - Core Principles

## Core Principle
**If you cannot prove an issue exists with concrete evidence, do not report it.**

## 1. Defensive Programming Requests
**Never suggest** defensive checks unless you can prove:
- The input comes from an untrusted source (ex: user/network)
- An actual path exists where invalid data reaches the code
- The current code can demonstrably fail

## 3. Unverifiable Assumptions
**Assume the author is wrong** and require proof they are correct.
- Research assumptions and claims in commit messages, comments and code, prove them correct.
- If the author makes claims without code evidence, treat them as unverified.

### 3.1 Comment-Based Dismissals (MANDATORY)
**CRITICAL**: When dismissing an issue because a comment or documentation says the code behaves a certain way, you MUST verify against the actual implementation.

## TASK POSITIVE.1 Verification Checklist
Before reporting ANY regression, verify:
1. **Can I prove this path executes?** (quote call chain)
2. **Is the bad behavior structurally possible?** (step-by-step path)
3. **Did I check the full context?** (callers 2-3 levels up)
4. **Is this actually wrong?** (check intent/documentation)
5. **Did I check for future fixes in the same patch series?**
