"""Extensible OSINT Investigation Playbooks teaching AI Agents human-like search tactics."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PlaybookStep(BaseModel):
    """A tactical step within an OSINT investigation playbook."""

    step_name: str
    strategy_tag: str
    description: str
    query_template: str
    priority_bonus: float = 0.1


class InvestigationPlaybook(BaseModel):
    """Structured playbook encoding human OSINT domain expertise."""

    id: str
    title: str
    description: str
    target_persona: str
    steps: list[PlaybookStep] = Field(default_factory=list)


BUILTIN_PLAYBOOKS: dict[str, InvestigationPlaybook] = {
    "vietnam_student_alumni": InvestigationPlaybook(
        id="vietnam_student_alumni",
        title="Truy vết Hồ sơ Học sinh / Sinh viên & Cựu sinh viên Việt Nam",
        description=(
            "Chiến thuật khoanh vùng từ Họ tên + Trường học/CLB/Cuộc thi + Niên khóa, "
            "mở rộng viết tắt tiếng Việt và suy luận handle qua hậu tố năm sinh."
        ),
        target_persona="Student / Alumni / Academic",
        steps=[
            PlaybookStep(
                step_name="Neo Trường học & Tổ chức",
                strategy_tag="school_anchor",
                description="Kết hợp biến thể tên có dấu/không dấu với tên trường và tên viết tắt.",
                query_template='("{name}" OR "{name_no_accent}") "{organization}"',
                priority_bonus=0.25,
            ),
            PlaybookStep(
                step_name="Săn Danh sách CLB / Giải thưởng / Đồ án",
                strategy_tag="academic_footprint",
                description="Tìm trong các trang công bố danh sách sinh viên, đồ án, CLB hoặc cuộc thi.",
                query_template='("{name}" OR "{name_no_accent}") ("sinh viên" OR "khóa" OR "CLB" OR "đồ án") "{organization}"',
                priority_bonus=0.20,
            ),
            PlaybookStep(
                step_name="Rà soát Tài khoản Lập trình / Nghề nghiệp",
                strategy_tag="social_dev_pivot",
                description="Tìm hồ sơ GitHub/LinkedIn khớp tên và trường học.",
                query_template='site:github.com OR site:linkedin.com/in ("{name}" OR "{name_no_accent}") "{organization}"',
                priority_bonus=0.18,
            ),
        ],
    ),
    "developer_digital_footprint": InvestigationPlaybook(
        id="developer_digital_footprint",
        title="Truy vết Dấu chân Số Lập trình viên & Kỹ sư Công nghệ",
        description=(
            "Đi từ username/email -> GitHub commits -> Phân tích múi giờ hoạt động UTC -> "
            "Giải phẫu cấu trúc đặt nick để bắt tài khoản chéo."
        ),
        target_persona="Software Engineer / Security Researcher",
        steps=[
            PlaybookStep(
                step_name="Quét Mã nguồn & Commit Công khai",
                strategy_tag="code_artifact_pivot",
                description="Tìm username hoặc email trên các nền tảng lưu trữ mã nguồn.",
                query_template='site:github.com OR site:gitlab.com "{alias_or_name}"',
                priority_bonus=0.28,
            ),
            PlaybookStep(
                step_name="Truy vết Writeup / Blog Kỹ thuật",
                strategy_tag="tech_blog_pivot",
                description="Tìm các bài viết kỹ thuật, CTF writeup, Viblo, Medium công khai.",
                query_template='("{name}" OR "{alias_or_name}") (site:viblo.asia OR site:medium.com OR "writeup" OR "portfolio")',
                priority_bonus=0.20,
            ),
        ],
    ),
    "mystery_alias_unmasking": InvestigationPlaybook(
        id="mystery_alias_unmasking",
        title="Giải mã Tài khoản Ẩn danh qua Giải phẫu Handle & Văn phong",
        description=(
            "Khi chỉ biết một biệt danh hoặc đoạn văn bản: phân tách gốc chữ + năm sinh trong nick, "
            "kết hợp so khớp Stylometry và tìm nút cầu nối 2-hop."
        ),
        target_persona="Alias / Pseudonymous Profile",
        steps=[
            PlaybookStep(
                step_name="Truy tìm Biến thể Handle Xuyên Nền tảng",
                strategy_tag="handle_anatomy_sweep",
                description="Tìm kiếm chính xác handle và gốc chữ cái đi kèm hậu tố năm.",
                query_template='"{alias_or_name}" OR "{core_handle}"',
                priority_bonus=0.25,
            ),
        ],
    ),
}


class PlaybookRegistry:
    """Manages built-in and user-taught OSINT playbooks."""

    def __init__(self) -> None:
        self._playbooks: dict[str, InvestigationPlaybook] = dict(BUILTIN_PLAYBOOKS)

    def list_playbooks(self) -> list[InvestigationPlaybook]:
        return list(self._playbooks.values())

    def get_playbook(self, playbook_id: str) -> InvestigationPlaybook:
        return self._playbooks.get(playbook_id, BUILTIN_PLAYBOOKS["vietnam_student_alumni"])

    def register_playbook(self, playbook: InvestigationPlaybook) -> InvestigationPlaybook:
        self._playbooks[playbook.id] = playbook
        return playbook
