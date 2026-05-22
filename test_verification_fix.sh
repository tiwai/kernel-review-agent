#!/bin/bash
# Test script to verify the verification improvements

echo "Testing verification improvements for commit 7172c6b1e3a0"
echo "============================================================"
echo ""

# Test 1: Verify the commit exists and file is present
echo "1. Checking if commit exists in SUSE downstream repo..."
cd ~/kernel/suse/expand/kernel
if git log --oneline -1 7172c6b1e3a0 > /dev/null 2>&1; then
    echo "   ✓ Commit 7172c6b1e3a0 found"
else
    echo "   ✗ Commit not found"
    exit 1
fi

echo ""
echo "2. Checking if vgem_fence.c exists at that commit..."
if git show 7172c6b1e3a0:drivers/gpu/drm/vgem/vgem_fence.c > /dev/null 2>&1; then
    echo "   ✓ File drivers/gpu/drm/vgem/vgem_fence.c exists at commit"
else
    echo "   ✗ File not found at commit"
    exit 1
fi

echo ""
echo "3. To test with the actual review agent, run:"
echo "   cd ~/kernel/suse/expand/kernel"
echo "   ~/tmp/claude-test9/kernel_review_agent.py --commit 7172c6b1e3a0 --enable-tools --verbose --debug"
echo ""
echo "The verification prompts should now include:"
echo "  - Commit SHA: 7172c6b1e3a0"
echo "  - Modified files list"
echo "  - Examples: git_show(commit=\"7172c6b1e3a0\", path=\"drivers/gpu/drm/vgem/vgem_fence.c\")"
echo ""
echo "This should prevent the 'file does not exist' error."
