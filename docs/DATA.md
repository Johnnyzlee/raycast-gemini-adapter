# Data, video inputs and retention

[English README](../README.md) · [中文说明](../README.zh-CN.md)

## Where data goes

| Data | Location / handling |
| --- | --- |
| API key | Read from the selected entry in the local Raycast provider file; sent in the header to the fixed Google API origin |
| Questions and tool results | Sent to Google as model context |
| Requested images/documents | Read within allowed roots and sent as native input, including original supported binary formats |
| Local video | Full file sent to Google's Files API, then referenced by native video input |
| Native history and sources | Private local SQLite state; contains conversation and file content |
| Video cache | Credential/content hash, Google file ID/URI and expiry; no second local video copy |
| Service log | Operational metadata such as model, tool types, token counts and error category |
| Provider backup | Private local file containing the original configuration and credentials |

State directories use `700`, SQLite and management-created configuration backups use `600`. Source-presentation pages use unguessable loopback URLs, preserve Google HTML/CSS and set a restrictive content-security policy. Keep these links local to the chat.

## File formats

- Images: PNG, JPEG and WebP; data attachments and explicitly named local images.
- Documents: PDF; Word/PowerPoint/Excel (modern and legacy extensions); OpenDocument text, sheet and presentation formats.
- UTF-8 text: txt, md, csv, tsv, json, html, xml, tex, py, js and ts.
- Local video containers: mp4, m4v, mpeg, mpg, mov, avi, webm, wmv, flv and 3gp. `ffprobe` checks actual streams and duration; Google also needs a supported codec.

PDF, DOCX and PNG are included in representative real tests. An accepted extension does not establish that every variant has been tested. Images/documents have an 18 MiB local cap and ordinary requests a 64 MiB body cap. Allowed roots and resolved symlinks are checked; common credential directories and `.env` paths are excluded.

## Three video inputs

**YouTube.** Public accessible videos go directly to Google's native video input. Login, membership, private/unlisted access and platform restrictions are handled by Google. This adapter does not download other platforms or forward cookies.

**HTTPS video file.** The local preflight allows standard port 443, rejects credential-bearing/private targets, pins a public IP with TLS hostname verification, rechecks up to three redirects, and reads at most 4 KiB. It requires a supported video MIME and confirmed size up to 15 MB. For larger files, use an allowed local copy.

Some proxies map public domain DNS results entirely to `198.18.0.0/15`. In that case the adapter makes no local content connection; a URL with a recognized video suffix goes to Google's native URL reader for accessibility, format and size validation. The tool result records that delegated validation. Other reserved/private addresses, literal proxy-range IPs and mixed public/private DNS remain rejected.

**Local absolute path.** The user supplies a path or names the file. The adapter checks allowed roots, format, size and duration, uploads resumable chunks, and waits for `ACTIVE`. Default caps are 256 MiB and three hours. A SHA-256 cache is scoped to credentials; concurrent same-file uploads in one running service share a lock. Missing or expired cloud objects are re-uploaded on demand.

## Processing choices

| Mode | Use | Parameters |
| --- | --- | --- |
| Static, normal | Short summaries and broad overviews | Low resolution, 1 FPS, frames and audio |
| Static, high | Small text, charts and detailed motion | High resolution, 2 FPS, frames and audio |
| Agentic, explicit request | On-demand navigation of native video | Google decides what layers and segments to load |

Static `start` / `end` offsets select the requested interval. Uploading a local source still transfers the whole file. Timestamps refer to the original timeline and are model estimates. Sampling can omit brief events; choose a narrow high-detail interval when precision matters. Agentic has different reading/thinking costs and does not imply that both image and sound layers were loaded. This implementation requires static mode for clipped ranges.

## Retention and cleanup

- **History:** three days since a checkpoint was updated; at most 100 checkpoints. The cumulative native-payload budget is about 256 MiB, retaining the newest checkpoint. SQLite may retain allocated space for reuse. Newer snapshots can contain older conversation content.
- **Source events:** three days per event, at most 160 retained. Reads/saves apply expiry and pruning.
- **Uploaded video:** Google normally expires Files API objects after 48 hours. Metadata is rechecked before reuse; without an explicit expiry, the local reference uses a conservative 47-hour window. At most 50 active cached upload records per account.
- **Background interactions:** cancellation is attempted on failure/timeout; deletion is requested after completion. A cleanup failure is included in the tool result. Files remain separately reusable until expiry or cleanup.

```sh
# Delete this adapter's registered video uploads for the selected account
./.venv/bin/python manage.py cleanup-video-files

# Clear local conversations, sources and suggestion pages; retain upload metadata
./.venv/bin/python manage.py stop
./.venv/bin/python manage.py clear-history
./.venv/bin/python manage.py start
```

Cloud cleanup does not delete local source files. After expiry/deletion, a new analysis needs the original source again. Historical answer text can still be discussed while its local checkpoint remains available.

## Official references

Checked 2026-11-26: [Video inputs](https://aistudio.google.com/docs/video-understanding), [file input methods](https://aistudio.google.com/docs/file-input-methods), [Files API](https://aistudio.google.com/docs/files), [background execution](https://aistudio.google.com/docs/background-execution), [Search](https://aistudio.google.com/docs/google-search), [Search display terms](https://aistudio.google.com/docs/terms#grounding-with-google-search).
