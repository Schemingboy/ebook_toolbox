import hashlib
from pathlib import Path


SINGLE_BOOK_DIRNAME = "单本好书"
FOUND_SECTION_HEADER = "已找到并复制的文件："


def resolve_output_dir(
    base_output_dir: Path | str,
    list_path: Path | str,
    book_names: list[str],
    from_clipboard: bool,
    clipboard_dir_name: str | None = None,
) -> Path:
    base_output_dir = Path(base_output_dir)
    list_path = Path(list_path)

    if len(book_names) <= 1:
        return base_output_dir / SINGLE_BOOK_DIRNAME

    if from_clipboard:
        if not clipboard_dir_name:
            raise ValueError("剪贴板模式缺少目录名")
        return list_path / clipboard_dir_name

    return base_output_dir / list_path.stem


def extract_previously_copied_books(result_content: str) -> set[str]:
    if FOUND_SECTION_HEADER not in result_content:
        return set()

    copied_section = result_content.split(FOUND_SECTION_HEADER, 1)[1].split("\n\n", 1)[0]
    books = set()
    for line in copied_section.strip().splitlines():
        if line.startswith("- 《") and "》" in line:
            book_name = line.split("《", 1)[1].split("》", 1)[0]
            books.add(book_name)
    return books


def extract_existing_copied_section(result_content: str) -> str:
    if FOUND_SECTION_HEADER not in result_content:
        return ""

    parts = result_content.split(FOUND_SECTION_HEADER, 1)
    if len(parts) < 2:
        return ""
    return parts[1].split("\n\n", 1)[0].strip()


def _file_hash(file_path: Path) -> str:
    """计算书单文件的内容哈希（MD5），用于判断文件是否修改过。"""
    try:
        return hashlib.md5(file_path.read_bytes()).hexdigest()[:12]
    except Exception:
        return ""


def _make_progress_entry(file_path: Path) -> str:
    """生成进度记录条目：文件路径:内容哈希"""
    return f"{file_path}:{_file_hash(file_path)}"


def _parse_progress_entry(entry: str) -> tuple[str, str]:
    """解析进度记录条目，返回 (文件路径, 哈希)。兼容旧格式（无哈希的纯路径）。"""
    if ":" in entry:
        parts = entry.rsplit(":", 1)
        if len(parts) == 2 and len(parts[1]) == 12:
            return parts[0], parts[1]
    return entry, ""


def classify_list_file(file_path: Path | str, processed_files: set[str], existing_dirs: set[str]) -> str:
    file_path = Path(file_path)
    current_hash = _file_hash(file_path)

    # 遍历已处理记录，匹配路径
    for entry in processed_files:
        stored_path, stored_hash = _parse_progress_entry(entry)

        if str(file_path) == stored_path:
            if stored_hash:
                if current_hash == stored_hash:
                    return "processed"   # 内容没变，跳过
                else:
                    return "pending"     # 内容变了，重新处理
            return "processed"           # 旧格式（无哈希），跳过

    # 输出目录已存在，但文件没被处理过（或哈希不同）→ 处理它
    if file_path.stem.lower() in existing_dirs:
        # 检查是否已通过其他路径记录（例如旧文件被移动后重新创建）
        for entry in processed_files:
            stored_path, stored_hash = _parse_progress_entry(entry)
            if Path(stored_path).stem.lower() == file_path.stem.lower():
                if stored_hash and current_hash == stored_hash:
                    return "existing_dir"  # 内容一样，跳过
                else:
                    return "pending"       # 内容不同，处理
        # 同名目录已存在但无进度记录 → 视为已处理，跳过并补记进度（幂等恢复）
        return "existing_dir"

    return "pending"
