# Architecture and source recovery

[English README](../README.md) · [中文说明](../README.zh-CN.md)

## Request flow

1. Authenticate the loopback request using the selected provider's existing key.
2. Restore the longest matching native checkpoint, scoped by credential hash, model and optional `conversation_id`.
3. Merge new messages with native history. Add Google tools, adapter file/video functions and the Raycast functions declared for this request.
4. Call the selected model. Execute adapter functions locally; return client functions to Raycast.
5. Save native history and the source ledger together before handing off. On the next request, restore them before adding Raycast's results.
6. Stream visible text and known references incrementally. Append late sources, tool outcomes and usage, then store the completed checkpoint. JSON mode buffers and validates the final object.

The implementation keeps the current HTTP/SSE envelope on errors, including `id`, `created`, `model`, `choices`, readable content and `[DONE]`. An upstream error therefore remains readable to the client.

## Tool boundaries

| Tool | Execution and inputs |
| --- | --- |
| Google Search / URL Context | Main native conversation; actual grounding and URL status returned by Google |
| `gemini_google_maps` | Separate same-model request with native Maps; requires an actual Maps invocation and source result |
| `gemini_run_python` | Separate same-model code-execution request carrying relevant document data |
| `gemini_open_document` / `gemini_view_image` | Read explicit user-authorized paths within `allowed_roots`; append raw supported file content |
| `gemini_analyze_video` | Native Interactions video input; local video first uploads through Files API |
| Raycast functions | Passed back only when declared in the current request; executed by Raycast |

Maps and Python are separated. When native history contains PDF/Office data, the main call omits code execution and uses the Python function instead. A file path in a webpage or tool result does not authorize an additional local upload.

## Source ledger

`State.history_metadata` accompanies `State.histories`; the original native-history data shape is retained for compatibility. The metadata contains:

- **Records:** stable `S…` identifiers, actual URL or file name, source kind and video range/mode where applicable.
- **Events:** task ID, tool, outcome, related record IDs and time; Google support mappings and original search-suggestion HTML when returned.
- **Usage:** one record per completed main/child call, retained across a Raycast handoff and reset for a new user task.

`native_events` merges streamed grounding metadata while remapping chunk indices. `ReferenceStream` converts known source markers into stable numeric links as text arrives, including markers split across chunks. It uses stored URLs and leaves ordinary Markdown and Unicode intact. Late metadata is retained in the final source list; already-sent text is never rewritten.

The ledger retains internal `S…` IDs and persistent display numbers. Each visible source uses an acquired title or URL-matched structured snippet, shortened extractively when useful. Known publisher domains supply website names. A domain-only result has no article summary; model answer text is not used as a substitute for acquired source content.

At a handoff, Google can return `toolResponse.search_suggestions` before it returns citation URLs. The adapter preserves those suggestions and records a partial search result; later grounding data adds real sources. Citation metadata alone is not counted as a fresh tool execution.

File sources use actual file names. Python is execution evidence. Raycast results are recorded by tool name and result type, with explicit errors labelled as failures; their private contents are not copied into the tool-status footer.

## Follow-ups and model switching

A same-task external-tool continuation restores its task, sources and usage. A new user question starts a new task, with historical sources available for relevant citations. Sources not selected for the answer stay out of the historical footer.

Switching among the three supported models restores native content and sources from the longest matching checkpoint. Opaque signatures from another model are removed; old tool results are restored as historical material.

If the client omits `conversation_id`, state is bound to the visible transcript prefix and tool IDs/arguments. Two identical prefixes under the same credential cannot be separated. Missing or expired native tool context produces a readable request to start a fresh chat and reload the material.

## Video-result recovery

A successful video call is saved immediately in `recovery_checkpoints`, together with signed native history, completed local-tool results, pending tool calls, sources and the usage ledger. Subsequent local results advance that checkpoint. A final-answer failure or client disconnect leaves it available after restart; partial answers are not stored as completed conversations.

Automatic retry requires the same nonempty conversation ID, credentials, model, request and processing settings. Local files are rechecked by content hash and access rules. Without a conversation ID, retrying identical text starts fresh; an explicit `继续恢复 <32-character code>` selects the saved result within its original credential/model/session scope. Keep this recovery code private. Failed, cancelled, incomplete or expired analyses are not reusable. New questions or intervals cause necessary new calls; follow-ups asking only about an existing summary can use ordinary history. Explicit reanalysis bypasses recovery.

Checkpoints expire three days after the original recoverable task began, with at most 100 records and an approximately 64 MiB cumulative payload budget; the newest record is retained even if larger. Reads and usage refreshes do not extend the expiry. Upload caching is separate: reusing a cloud file still incurs new inference when analysis runs again.

Previously incurred usage is retained once, while the retry's new generation usage is reported separately. Missing usage remains unknown. Identical active requests are serialized within one service; cancelling a waiting request does not start another analysis.

## Code map

| File | Responsibility |
| --- | --- |
| `adapter.py` | Protocol, native generation, dispatch, state and SSE |
| `configuration.py` | Portable defaults and configuration validation |
| `provenance.py` | Source records, event outcomes, citation rendering and suggestions |
| `video_tools.py` | Input validation, uploads, processing, bounded background interactions |
| `usage_cost.py` | Usage normalization and dated token estimates |
| `manage.py` | Install, ownership checks, lifecycle, rollback and cleanup |

The ordinary generation transport waits at most 120 seconds per blocked read, within the overall request deadline. Video interactions are polled with cancellation/deadline checks and deleted after completion; uploads may remain available for reuse.
