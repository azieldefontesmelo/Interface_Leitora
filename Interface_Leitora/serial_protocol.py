"""Decodificação incremental do protocolo serial da leitora OSL.

O equipamento usa ``&`` como terminador de frame. A camada serial pode
entregar um frame em vários pedaços ou vários frames na mesma leitura; por
isso a montagem precisa acontecer sobre bytes, antes da decodificação ASCII.
"""

from __future__ import annotations


class SerialFrameDecoder:
    """Monta frames delimitados por ``&`` sem perder fragmentos.

    A leitora usa frames pequenos. O limite evita que uma porta com ruído ou
    um equipamento com protocolo diferente faça o buffer crescer
    indefinidamente enquanto nenhum terminador chega.
    """

    delimiter = b"&"

    def __init__(self, *, max_buffer_size: int = 64 * 1024) -> None:
        if max_buffer_size < 1:
            raise ValueError("max_buffer_size deve ser positivo")
        self.max_buffer_size = max_buffer_size
        self._buffer = bytearray()
        self.discarded_bytes = 0

    @property
    def pending_size(self) -> int:
        return len(self._buffer)

    def reset(self) -> None:
        self._buffer.clear()
        self.discarded_bytes = 0

    def feed(self, data: bytes | bytearray | memoryview) -> list[bytes]:
        """Adiciona bytes e devolve todos os frames completos encontrados."""

        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("data deve ser bytes-like")
        if data:
            self._buffer.extend(data)

        frames: list[bytes] = []
        while True:
            delimiter_index = self._buffer.find(self.delimiter)
            if delimiter_index < 0:
                break
            frame = bytes(self._buffer[:delimiter_index])
            del self._buffer[: delimiter_index + len(self.delimiter)]
            if frame:
                frames.append(frame)

        if len(self._buffer) > self.max_buffer_size:
            # Mantém o último início de frame plausível. Assim, depois de
            # ruído ou de uma transmissão interrompida, um frame novo ainda
            # pode ser reconhecido sem limpar dados válidos seguintes.
            last_start = self._buffer.rfind(b"#")
            if last_start > 0:
                self.discarded_bytes += last_start
                del self._buffer[:last_start]
            else:
                self.discarded_bytes += len(self._buffer)
                self._buffer.clear()

        return frames
