# SunRPC Subsystem Delta

## Overview

SunRPC (net/sunrpc/) provides RPC transport for NFS. Covers client (rpc_clnt, rpc_task, xprt) and server (svc_serv, svc_rqst, svc_xprt) with TCP/UDP/RDMA and RPCSEC_GSS. Reference ../callstack.md for caller/callee traversal and lock validation.

## File Applicability

| Files | Domain |
|-------|--------|
| svc.c, svc_xprt.c, clnt.c, sched.c, xprt.c | Core |
| svcsock.c, xprtsock.c | Socket |
| xprtrdma/svc_rdma_*.c, xprtrdma/*.c | RDMA |
| auth_gss/*.c, svcauth_gss.c, gss_krb5_*.c | GSS |

---

## Core Infrastructure Patterns [SUNRPC-CORE]

- **SUNRPC-CORE-001**: Hold svc_xprt_get/xprt_get before queue_work; release in handler. (use-after-free)
- **SUNRPC-CORE-002**: Check XPT_CLOSE/XPT_DEAD (server) or XPRT_CONNECTED/XPRT_CLOSING (client) before transport access.
- **SUNRPC-CORE-003**: svc_exit_thread() required on all thread stop paths to clear SP_VICTIM_REMAINS; controller calls it when kthread_stop() wins race.
- **SUNRPC-CORE-004**: Check rq_next_page < rq_page_end before svc_rqst_replace_page(). (buffer overflow)
- **SUNRPC-CORE-005**: Every svc_handle_xprt() exit path must call svc_xprt_received() to clear XPT_BUSY, including reservation failures.
- **SUNRPC-CORE-006**: On defer: set dr->xprt_ctxt = rqstp->rq_xprt_ctxt then rqstp->rq_xprt_ctxt = NULL; reverse on revisit. (double-free)
- **SUNRPC-CORE-007**: Each call_* state must set tk_action; do not modify tk_status when tk_action is NULL (task exiting).
- **SUNRPC-CORE-008**: xprt_release() must occur on all paths after xprt_reserve(). (slot exhaustion)
- **SUNRPC-CORE-009**: Hold transport_lock when updating xprt->cong.
- **SUNRPC-CORE-010**: Clamp rq_timeout after shift: if (rq_timeout > to_maxval) rq_timeout = to_maxval. (integer overflow)
- **SUNRPC-CORE-011**: Use set_bit/clear_bit, not __set_bit/__clear_bit on rq_flags. (race with svc_xprt_enqueue)
- **SUNRPC-CORE-012**: Release old xprt reference before assigning new transport. (reference leak)

---

## Socket Transport Patterns [SUNRPC-SOCK]

- **SUNRPC-SOCK-001**: TCP may return fewer bytes; loop until complete or use MSG_WAITALL for fixed-size reads.
- **SUNRPC-SOCK-002**: Validate incoming record size before allocation. (memory exhaustion)
- **SUNRPC-SOCK-003**: Child sockets inherit sk_user_data from listener; check sk->sk_state == TCP_LISTEN BEFORE dereferencing sk_user_data.
- **SUNRPC-SOCK-004**: Teardown order: lock_sock(); xs_restore_old_callbacks(); sk->sk_user_data = NULL; release_sock(); then sock_release().
- **SUNRPC-SOCK-005**: tcp_sock_set_cork(sk, false) on all paths including errors. (cork leak)
- **SUNRPC-SOCK-006**: Use xprt_reconnect_delay() and queue_delayed_work, not immediate queue_work. (connection storm)
- **SUNRPC-SOCK-007**: Use memalloc_nofs_save/restore around socket operations. (deadlock in reclaim)
- **SUNRPC-SOCK-008**: Use smp_mb__after_atomic() between related flag changes.
- **SUNRPC-SOCK-009**: Add clear_bit in xs_sock_reset_state_flags() for any new XPRT_SOCK_* flags.
- **SUNRPC-SOCK-010**: svc_write_space() must call svc_xprt_enqueue() when write space available; server stops reading when it cannot write.

---

## RDMA Transport Patterns [SUNRPC-RDMA]

- **SUNRPC-RDMA-001**: DMA mappings must persist until completion callback fires; check ib_dma_map_sg() return (mr_nents == 0 is failure); unmap in completion handler.
- **SUNRPC-RDMA-002**: MRs must complete invalidation before reuse; frwr_unmap_async() does not block—do not reuse MR immediately after async invalidate.
- **SUNRPC-RDMA-003**: Only wr_cqe and status reliable in work completion; check wc->status == IB_WC_SUCCESS before accessing other fields.
- **SUNRPC-RDMA-004**: On IB_WC_WR_FLUSH_ERR, device may be gone; do not call ib_dma_* in flush error paths.
- **SUNRPC-RDMA-005**: Completion handler can fire immediately after ib_post_send(); copy context fields to stack before posting if needed after the call.
- **SUNRPC-RDMA-006**: set_bit(XPT_CLOSE) BEFORE svc_rdma_*_ctxt_put() to prevent racing completion from reallocating freed context.
- **SUNRPC-RDMA-007**: ESTABLISHED takes reference via rpcrdma_ep_get(); DISCONNECTED releases via rpcrdma_ep_put(); DEVICE_REMOVAL/ADDR_CHANGE may fire before ESTABLISHED—track whether reference was taken.
- **SUNRPC-RDMA-008**: If teardown calls rpcrdma_regbuf_dma_unmap(), verify reconnect path remaps before posting receives.
- **SUNRPC-RDMA-009**: Call rpcrdma_post_recvs() BEFORE rpcrdma_update_cwnd(); opening credits wakes senders who need posted receives.

---

## GSS Authentication Patterns [SUNRPC-GSS]

- **SUNRPC-GSS-001**: Hold sd_lock for all sequence window operations; verify arithmetic handles overflow near MAXSEQ and underflow in sd_max - GSS_SEQ_WIN.
- **SUNRPC-GSS-002**: gss_svc_searchbyctx() returns referenced entry; call cache_put() after use; do not access after put.
- **SUNRPC-GSS-003**: Check gss_verify_mic/gss_wrap/gss_unwrap return status; abort on any GSS_S_* error. (authentication bypass)
- **SUNRPC-GSS-004**: For Kerberos v2 (RFC 4121), au_ralign != au_rslack; account for GSS_KRB5_TOK_HDR_LEN + checksum. (buffer overrun)
- **SUNRPC-GSS-005**: Server: get_group_info() before using rsci->cred, release via free_svc_cred(). Client: put_rpccred() only after all use complete.
- **SUNRPC-GSS-006**: __gss_find_upcall() must match uid + service + in-flight state; insufficient criteria pairs wrong upcall/downcall.
- **SUNRPC-GSS-007**: Skip re-verification for rqstp->rq_deferred requests; already verified on first pass.

---

## Network Namespace

Never use &init_net or current->nsproxy->net_ns. Use:
- Server: xprt->xpt_net, serv->sv_net
- Client: xprt->xprt_net, clnt->cl_xprt->xprt_net
- Socket creation: sock_create_kern(net, ...)
- RDMA: rdma_create_id(net, ...), rdma_dev_access_netns()

---

## Quick Reference

**Transport state flags:**
- Server: XPT_BUSY, XPT_CLOSE, XPT_DEAD, XPT_DATA, XPT_CONN
- Client: XPRT_CONNECTED, XPRT_CONNECTING, XPRT_CLOSING

**Reference counting:** svc_xprt_get/put, xprt_get/put, rpc_get_task/put_task, gss_get_ctx/put_ctx

---

## Stop Conditions

Flag for expert review when:
- Service/pool allocation or thread management modified
- New XPT_*/XPRT_* flags introduced
- FSM state transitions or slot allocation algorithm changed
- Callback registration/deregistration affected
- FRWR registration/invalidation sequencing modified
- CM event handler or completion ordering changed
- GSS context establishment or sequence window logic changed
- Cryptographic algorithm selection or upcall mechanism modified
- Changes exceed 100 lines touching multiple core files
