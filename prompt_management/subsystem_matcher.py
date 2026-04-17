"""Match code changes to subsystem guides."""

import re
from typing import List, Tuple


class SubsystemMatcher:
    """Match diff content to applicable subsystem guides."""

    def __init__(self, prompts_dir: str = "prompts"):
        """
        Initialize subsystem matcher.

        Args:
            prompts_dir: Directory containing prompt files
        """
        self.prompts_dir = prompts_dir
        self.triggers = self._load_triggers()

    def _load_triggers(self) -> List[Tuple[str, List[str], str]]:
        """
        Load subsystem triggers from subsystem/subsystem.md.

        Returns:
            List of (subsystem_name, trigger_patterns, guide_filename) tuples
        """
        # Hardcoded trigger mappings from subsystem/subsystem.md
        # Format: (subsystem_name, triggers_list, guide_file)
        return [
            ("Networking", ["net/", "drivers/net/", "skb_", "socket"], "networking.md"),
            ("MM Page Tables", ["pte_", "pmd_", "pud_", "set_pte", "ptep_", "tlb_", "page_vma_mapped_walk", "walk_page_range", "zap_pte_range", "mm/memory.c", "mm/mprotect.c", "mm/pagewalk.c"], "mm-pagetable.md"),
            ("MM Folio/Page Cache", ["folio_", "page_folio", "compound_head", "filemap_", "xa_", "xas_", "page_cache_", "mm/filemap.c", "mm/swap.c", "mm/truncate.c"], "mm-folio.md"),
            ("MM Large Folios/THP/Hugetlb", ["huge_memory", "hugetlb", "split_huge_", "folio_test_large", "hstate", "mm/huge_memory.c", "mm/hugetlb.c", "mm/memory-failure.c"], "mm-largepage.md"),
            ("MM VMA Operations", ["vma_", "mmap_", "vm_area_struct", "vm_flags", "anon_vma", "maple_tree", "mm/vma.c", "mm/mmap.c", "mm/mmap_lock.c"], "mm-vma.md"),
            ("MM Allocation", ["alloc_pages", "__GFP_", "kmalloc", "kmem_cache_", "slub", "vmalloc", "zone_watermark", "mempool", "memblock", "mm/page_alloc.c", "mm/slub.c", "mm/vmalloc.c"], "mm-alloc.md"),
            ("MM Reclaim/Swap/Migration", ["vmscan", "shrink_", "lru_", "swap_", "shmem_", "mem_cgroup_", "writeback", "migrate_", "mm/vmscan.c", "mm/swap_state.c", "mm/migrate.c", "mm/memcontrol.c"], "mm-reclaim.md"),
            ("VFS", ["inode", "dentry", "vfs_", "fs/"], "vfs.md"),
            ("Locking", ["spin_lock", "mutex_", "rwsem", "seqlock", "seqcount"], "locking.md"),
            ("Scheduler", ["kernel/sched/", "sched_", "schedule", "wakeup"], "scheduler.md"),
            ("Timers", ["timer_list", "timer_setup", "mod_timer", "del_timer", "hrtimer", "delayed_work"], "timers.md"),
            ("BPF", ["kernel/bpf/", "tools/lib/bpf/", "tools/testing/selftests/bpf", "bpf", "verifier"], "bpf.md"),
            ("RCU", ["rcu", "call_rcu", "synchronize_rcu", "kfree_rcu", "kvfree_call_rcu"], "rcu.md"),
            ("Encryption", ["crypto", "fscrypt_"], "fscrypt.md"),
            ("Tracing", ["trace_", "tracepoint"], "tracing.md"),
            ("Workqueue", ["kernel/workqueue.c", "work_struct"], "workqueue.md"),
            ("Syscalls", ["SYSCALL_DEFINE", "copy_from_user", "copy_to_user", "get_user", "put_user"], "syscall.md"),
            ("btrfs", ["fs/btrfs/"], "btrfs.md"),
            ("DAX", ["dax"], "dax.md"),
            ("Block/NVMe", ["block", "nvme"], "block.md"),
            ("DRM/GPU", ["drivers/gpu/drm/", "drm_atomic_", "drm_crtc_", "hwseq", "hw_sequencer"], "drm.md"),
            ("NFSD", ["fs/nfsd/", "fs/lockd/"], "nfsd.md"),
            ("SunRPC", ["net/sunrpc/"], "sunrpc.md"),
            ("io_uring", ["io_uring/", "io_uring_", "io_ring_", "io_sq_", "io_cq_", "io_wq_", "IORING_"], "io_uring.md"),
            ("Cleanup API", ["__free", "guard(", "scoped_guard", "DEFINE_FREE", "DEFINE_GUARD", "no_free_ptr", "return_ptr"], "cleanup.md"),
            ("Power Domains", ["drivers/pmdomain/", "pm_genpd_", "of_genpd_", "exynos_pd_"], "pmdomain.md"),
            ("PM Runtime", ["include/linux/pm_runtime.h", "pm_runtime_", "__pm_runtime_", "rpm_idle", "rpm_suspend", "rpm_resume"], "pm.md"),
            ("Sysfs", ["fs/sysfs/", "sysfs_create_group", "sysfs_update_group", "attribute_group", "is_visible"], "sysfs.md"),
            ("CXL", ["drivers/cxl/", "cxl_", "hmat_get_extended_linear_cache_size"], "cxl.md"),
            ("Bluetooth", ["net/bluetooth/", "hci_", "HCI_LE_ADV", "adv_instances", "cur_adv_instance"], "bluetooth.md"),
            ("TTY/Serial", ["drivers/tty/", "uart_add_one_port", "uart_ops", "serial_core"], "tty.md"),
            ("PCI", ["drivers/pci/", "pci_epc_", "pci_epf_", "pci_ep_"], "pci.md"),
            ("SMB/ksmbd", ["fs/smb/server/", "ksmbd_", "smb_direct_"], "smb-ksmbd.md"),
            ("Open Firmware", ["drivers/of/", "of_node", "of_find_", "of_get_", "of_parse_", "for_each_child_of_node", "for_each_available_child_of_node", "of_node_put", "of_node_get"], "of.md"),
            ("Perf Tools", ["tools/perf/", "openat", "fdopendir", "closedir"], "perf.md"),
        ]

    def match_diff(self, files: List[str], diff_content: str) -> List[str]:
        """
        Match diff against subsystem triggers.

        Args:
            files: List of changed file paths
            diff_content: Full diff content

        Returns:
            List of subsystem guide filenames to load
        """
        matched_guides = set()

        for subsystem_name, triggers, guide_file in self.triggers:
            if self._matches_triggers(triggers, files, diff_content):
                matched_guides.add(guide_file)

        return sorted(list(matched_guides))

    def _matches_triggers(
        self,
        triggers: List[str],
        files: List[str],
        diff_content: str
    ) -> bool:
        """
        Check if any trigger matches the diff.

        Args:
            triggers: List of trigger patterns (paths, function prefixes, symbols)
            files: List of changed file paths
            diff_content: Full diff content

        Returns:
            True if any trigger matches
        """
        for trigger in triggers:
            # Check file path patterns
            for filepath in files:
                if trigger in filepath:
                    return True

            # Check diff content for function names and symbols
            # Use word boundaries to avoid partial matches
            pattern = r'\b' + re.escape(trigger)
            if re.search(pattern, diff_content):
                return True

        return False
