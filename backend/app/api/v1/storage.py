"""Local and development object storage endpoints for direct client uploads and streaming downloads."""

from __future__ import annotations

import hashlib
from fastapi import APIRouter, Request, Response, status

from backend.app.infrastructure.storage import get_local_storage_client

router = APIRouter(prefix="/storage", tags=["Storage (Local Development)"])


@router.put("/upload/{storage_key:path}")
@router.post("/upload/{storage_key:path}")
async def upload_storage_object(storage_key: str, request: Request) -> Response:
    """Accept binary upload payload from pre-signed URL and save to local storage client."""
    client = get_local_storage_client()
    body = await request.body()
    content_type = request.headers.get("content-type", "application/octet-stream")
    await client.put_object(storage_key, body, content_type)
    etag = hashlib.md5(body, usedforsecurity=False).hexdigest()
    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "ETag": f'"{etag}"',
            "Access-Control-Expose-Headers": "ETag",
        },
    )


@router.put("/multipart/{upload_id}/part/{part_number}")
async def upload_multipart_part(
    upload_id: str, part_number: int, request: Request
) -> Response:
    """Accept multipart upload chunk and store under the session upload ID."""
    client = get_local_storage_client()
    body = await request.body()
    etag = client.store_multipart_part(upload_id, part_number, body)
    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "ETag": f'"{etag}"',
            "Access-Control-Expose-Headers": "ETag",
        },
    )


@router.get("/download/{storage_key:path}")
async def download_storage_object(storage_key: str, request: Request) -> Response:
    """Stream stored binary object payload back to authorized clients or media players."""
    client = get_local_storage_client()
    metadata = await client.get_object_metadata(storage_key)
    if metadata is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Object not found")

    data = await client.get_object_bytes(storage_key)
    etag = metadata.etag or hashlib.md5(data, usedforsecurity=False).hexdigest()

    range_header = request.headers.get("range")
    if range_header and range_header.startswith("bytes="):
        byte_range = range_header[6:].split("-")
        start = int(byte_range[0]) if byte_range[0] else 0
        end = int(byte_range[1]) if len(byte_range) > 1 and byte_range[1] else len(data) - 1
        chunk = data[start : end + 1]
        return Response(
            content=chunk,
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=metadata.content_type,
            headers={
                "Content-Range": f"bytes {start}-{end}/{len(data)}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(chunk)),
                "ETag": f'"{etag}"',
            },
        )

    return Response(
        content=data,
        status_code=status.HTTP_200_OK,
        media_type=metadata.content_type,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(len(data)),
            "ETag": f'"{etag}"',
            "Content-Disposition": "inline",
        },
    )


@router.head("/download/{storage_key:path}")
async def head_storage_object(storage_key: str) -> Response:
    """Return object presence and length headers for validation."""
    client = get_local_storage_client()
    metadata = await client.get_object_metadata(storage_key)
    if metadata is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    return Response(
        status_code=status.HTTP_200_OK,
        headers={
            "Content-Length": str(metadata.content_length),
            "Content-Type": metadata.content_type,
            "ETag": f'"{metadata.etag}"' if metadata.etag else "",
            "Accept-Ranges": "bytes",
        },
    )


v1_storage_router = router
