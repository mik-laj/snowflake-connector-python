#
# Copyright (c) 2012-2021 Snowflake Computing Inc. All right reserved.
#

from __future__ import division

import base64
import gzip
import os
import shutil
import struct
import time
from io import BytesIO, open
from logging import getLogger
from typing import IO, Tuple

from Cryptodome.Hash import SHA256
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes

from .constants import UTF8

logger = getLogger(__name__)


class SnowflakeFileUtil(object):
    @staticmethod
    def get_digest_and_size(src: IO[bytes]) -> Tuple[str, int]:
        """Gets stream digest and size.

        Args:
            src: The input stream.

        Returns:
            Tuple of src's digest and src's size in bytes.
        """
        t1 = time.clock_gettime(time.CLOCK_THREAD_CPUTIME_ID)
        use_openssl_only = os.getenv("SF_USE_OPENSSL_ONLY", "False") == "True"
        CHUNK_SIZE = 16 * 4 * 1024
        if not use_openssl_only:
            m = SHA256.new()
        else:
            backend = default_backend()
            chosen_hash = hashes.SHA256()
            hasher = hashes.Hash(chosen_hash, backend)
        i = 0
        while True:
            if i % 3000 == 0:
                logger.debug(f"reading chunk, {i}")
            i += 1
            chunk = src.read(CHUNK_SIZE)
            if chunk == b"":
                break

            if not use_openssl_only:
                m.update(chunk)
            else:
                hasher.update(chunk)

        if not use_openssl_only:
            digest = base64.standard_b64encode(m.digest()).decode(UTF8)
        else:
            digest = base64.standard_b64encode(hasher.finalize()).decode(UTF8)

        size = src.tell()
        src.seek(0)
        t2 = time.clock_gettime(time.CLOCK_THREAD_CPUTIME_ID)
        logger.debug(f"done getting digest, took {t2 - t1} seconds")
        return digest, size

    @staticmethod
    def compress_with_gzip_from_stream(src_stream: IO[bytes]) -> Tuple[IO[bytes], int]:
        """Compresses a stream of bytes with GZIP.

        Args:
            src_stream: bytes stream

        Returns:
            A tuple of byte stream and size.
        """
        compressed_data = gzip.compress(src_stream.read())
        src_stream.seek(0)
        return BytesIO(compressed_data), len(compressed_data)

    @staticmethod
    def compress_file_with_gzip(file_name, tmp_dir):
        """Compresses a file with GZIP.

        Args:
            file_name: Local path to file to be compressed.
            tmp_dir: Temporary directory where an GZIP file will be created.

        Returns:
            A tuple of gzip file name and size.
        """
        base_name = os.path.basename(file_name)
        gzip_file_name = os.path.join(tmp_dir, base_name + "_c.gz")
        logger.debug("gzip file: %s, original file: %s", gzip_file_name, file_name)
        with open(file_name, "rb") as fr:
            with gzip.GzipFile(gzip_file_name, "wb") as fw:
                shutil.copyfileobj(fr, fw)
        SnowflakeFileUtil.normalize_gzip_header(gzip_file_name)

        statinfo = os.stat(gzip_file_name)
        return gzip_file_name, statinfo.st_size

    @staticmethod
    def normalize_gzip_header(gzip_file_name):
        """Normalizes GZIP file header.

        For consistent file digest, this removes creation timestamp and file name from the header.
        For more information see http://www.zlib.org/rfc-gzip.html#file-format

        Args:
            gzip_file_name: Local path of gzip file.
        """
        with open(gzip_file_name, "r+b") as f:
            # reset the timestamp in gzip header
            f.seek(3, 0)
            # Read flags bit
            flag_byte = f.read(1)
            flags = struct.unpack("B", flag_byte)[0]
            f.seek(4, 0)
            f.write(struct.pack("<L", 0))
            # Reset the file name in gzip header if included
            if flags & 8:
                f.seek(10, 0)
                # Skip through xlen bytes and length if included
                if flags & 4:
                    xlen_bytes = f.read(2)
                    xlen = struct.unpack("<H", xlen_bytes)[0]
                    f.seek(10 + 2 + xlen)
                byte = f.read(1)
                while byte:
                    value = struct.unpack("B", byte)[0]
                    # logger.debug('ch=%s, byte=%s', value, byte)
                    if value == 0:
                        break
                    f.seek(-1, 1)  # current_pos - 1
                    f.write(struct.pack("B", 0x20))  # replace with a space
                    byte = f.read(1)

    @staticmethod
    def get_digest_and_size_for_stream(src_stream: IO[bytes]) -> Tuple[str, int]:
        """Gets stream digest and size.

        Args:
            src_stream: The input source stream.

        Returns:
            Tuple of src_stream's digest and src_stream's size in bytes.
        """
        digest, size = SnowflakeFileUtil.get_digest_and_size(src_stream)
        logger.debug("getting digest and size for stream: %s, %s", digest, size)
        return digest, size

    @staticmethod
    def get_digest_and_size_for_file(file_name: str) -> Tuple[str, int]:
        """Gets file digest and size.

        Args:
            file_name: Local path to a file.

        Returns:
            Tuple of file's digest and file size in bytes.
        """
        digest, size = None, None
        with open(file_name, "rb") as src:
            digest, size = SnowflakeFileUtil.get_digest_and_size(src)
        logger.debug(
            "getting digest and size: %s, %s, file=%s", digest, size, file_name
        )
        return digest, size
