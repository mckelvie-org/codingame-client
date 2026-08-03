# Files: upload and download

Binary content — contribution cover images, puzzle test-case data — isn't carried inline in the
service API. It's referenced by numeric ID and moved through two servlets.

## Downloading

```python
async with CgClient() as client:
    result = await client.servlets.file_servlet(binary_id)
    path.write_bytes(result.content)
```

`CgDownloadFileResult` carries the bytes, the content type, and the filename from
`Content-Disposition` if the server sent one.

Content is returned as **bytes**, not text, and written to disk that way. Puzzle test-case files are
the reason: they are the server's own artifacts, and a local run has to feed a solution's stdin
exactly what CodinGame feeds it. Decoding and re-encoding is where that guarantee gets quietly lost.

Some files are publicly downloadable. `require_login=False` lets the server decide with a 401/403
rather than the client refusing up front.

The CLI equivalent:

```bash
cg api file-servlet <ID> > cover.png
```

## Uploading

```python
binary_id = await client.servlets.file_upload(data, filename="cover.png")
```

Returns the new object's ID, which you then reference from whatever you're saving — for a cover
image, `CgContributionData.cover_binary_id`.

```bash
cg api file-upload < cover.png
```

## A caution about orphans

An upload with nothing referencing it is an orphaned object on CodinGame's servers. A handful are
harmless; producing them in bulk — a test suite that uploads on every run, say — is the kind of
pattern that gets accounts flagged.

Uploads attached to something you're managing are fine. `cg contribution push` uploads a cover
image only when it has changed, and reuses the existing ID otherwise, precisely so that repeated
pushes don't leave a trail of dead objects.
