# Validation record

Date: **2026-11-26**. [English README](../README.md) · [中文说明](../README.zh-CN.md)

## Offline regression

The publication checkout passes **57 offline tests** on the local Python 3.14 environment. CI runs the same suite on Python 3.11 and 3.14. No real key or API is needed for this suite.

Coverage includes SSE success/error envelopes, null and empty message forms, parallel and sequential tool responses, source handoff and recovery, stream source-index remapping, historical versus new sources, model switching, credential/conversation scope, legacy/expired state, file authorization, upload reuse, private-address/redirect rejection, processing failure, cancellation, unknown usage, dated estimates, installer failure/concurrent-edit handling, service ownership and rollback preserving unrelated providers.

## Native API baseline

The runtime implementation from which this repository was prepared completed these real API checks on the same date, using public pages and synthetic files:

| Scenario | Observed result |
| --- | --- |
| Carbon, Neon, Hydrogen | Each read native local-video input |
| YouTube / direct HTTPS video / local path | All three input routes completed |
| Neon video | Summary, 4–8 second range, timestamped answers, historical follow-up and switch to Carbon completed |
| Search → Raycast tool → final → follow-up webpage | Sources and search suggestions survived the handoff |
| Maps + webpage | Actual map source and successful URL retrieval metadata retained |
| PDF + cloud Python | Document read and actual code-execution outcome verified |
| Image + DOCX | Synthetic shapes and document verification code recognized |
| Agentic video + document | Native Agentic processing and document read completed |

Checks used native invocation records, metadata, usage and known fixture contents. At a live search handoff, Google returned search suggestions before citation URLs; later continuation returned grounding sources. The exact earlier-source-URL-before-handoff regression is also exercised with deterministic API fixtures.

The original static fixture included generated colors/text and spoken audio. To keep distribution provenance simple, this repository ships source-generated images/documents and a video generator using original color cards plus mathematical tones. The generated video is not committed.

## Installation and release preparation

The portable installer adds configurable provider/config paths, service identity and ffprobe discovery. Its offline checks cover dry runs, occupied/existing installations, foreign checkout ownership, startup failures and endpoint rollback.

A separate source checkout, virtual environment, test provider file, temporary state, port and LaunchAgent identity are used for the local installation acceptance. Public-checkout API results and the completed installation record are appended after execution; private responses, credentials and machine-specific paths stay outside Git.

## Boundaries observed

- Google requests occasionally exceeded the bounded socket timeout. Explicit test retries succeeded; the adapter returned readable SSE errors for failed attempts. It does not automatically repeat billable generation calls.
- The initial direct-video sample returned HTTP 403. A verified accessible Google-hosted sample completed native video analysis.
- With fake-IP proxy DNS, local fetching was skipped and Google performed direct-URL validation; this behavior is recorded in the tool result.
- File expiration, timeout, invalid formats/sizes and processing failure have deterministic offline coverage. No test waits 48 hours for real expiry.
- Raycast UI access timed out during the runtime's previous acceptance. Interface tests establish HTTP/SSE behavior, not Raycast rendering. README/browser preview checks are separate from AI Chat UI checks.
- Without a stable client conversation ID, identical visible prefixes under the same credential share the same recovery key.

## Reproduce a paid check

```sh
./.venv/bin/python scripts/generate_fixtures.py
./.venv/bin/python scripts/generate_video.py
./.venv/bin/python test_video_live.py --settings settings.json --only video-hydrogen
```

Other selectors: `video-neon`, `video-carbon`, `youtube`, `direct`, `search-raycast-followup`, `maps-web`, `document-python`, `image-document`, `agentic-video-document`.

The runner uses an ephemeral loopback port and temporary state, restricts local file access to fixtures, and deletes its registered test uploads on completion. Raw outputs stay in ignored `local-evidence/`. Verify only the combinations relevant to a change before broadening paid tests.
