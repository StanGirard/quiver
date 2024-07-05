import os
from pathlib import Path
from uuid import UUID, uuid4


class QuivrFile:
    def __init__(
        self,
        id: UUID,
        original_filename: str,
        path: Path,
        brain_id: UUID,
        file_size: int | None = None,
        file_extension: str | None = None,
    ) -> None:
        self.id = id
        self.brain_id = brain_id
        self.path = path
        self.original_filename = original_filename
        self.file_size = file_size
        self.file_extension = file_extension

    @classmethod
    def from_path(cls, brain_id: UUID, path: str | Path):
        if isinstance(path, str):
            path = Path(path)

        if not path.exists():
            raise FileExistsError(f"file {path} doesn't exist")

        file_size = os.stat(path).st_size

        try:
            # NOTE: when loading from existing storage, file name will be uuid
            id = UUID(path.name)
        except ValueError:
            id = uuid4()

        return cls(
            id=id,
            brain_id=brain_id,
            path=path,
            original_filename=path.name,
            file_size=file_size,
            file_extension=path.suffix,
        )
