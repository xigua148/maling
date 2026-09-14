"""计划编辑器 —— 创建/编辑/删除项目计划，设置里程碑和任务清单。"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from gui import icons
from gui.qt_compat import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QComboBox, QProgressBar, QTreeWidget,
    QTreeWidgetItem, QFrame, Qt, QFont, QMessageBox, QInputDialog,
    QMenu, QListWidget, QListWidgetItem, QSize,
)
from gui.utils import theme_color

logger = logging.getLogger("maid_coder.gui")

DEFAULT_PLANS_DIR = Path.home() / ".maid_coder" / "plans"

# v2.1(V21-12/D-V21-06): 里程碑图标统一 —— 只记「图标名 + 尺寸 + theme_color 取色」，
# 字体不可用时回落原 emoji。
_MILESTONE_ICON_SIZE = 16


def _vector_icon(app_ctx, name: str, size: int, color):
    """取矢量 ``QIcon``；字体/名字不可用或渲染失败 → ``None``（调用方回落 emoji）。"""
    try:
        if not name or not icons.available() or not icons.has(name):
            return None
        ic = icons.icon(name, size, color)
        if ic is None or ic.isNull():
            return None
        return ic
    except Exception:
        return None


class Task:
    """任务数据模型。"""

    def __init__(self, id: str, name: str, completed: bool = False):
        self.id = id
        self.name = name
        self.completed = completed

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            completed=data.get("completed", False),
        )

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "completed": self.completed}


class Milestone:
    """里程碑数据模型。"""

    def __init__(
        self,
        id: str,
        name: str,
        deadline: str = "",
        tasks: Optional[List[Task]] = None,
    ):
        self.id = id
        self.name = name
        self.deadline = deadline
        self.tasks = tasks or []

    @property
    def progress(self) -> int:
        if not self.tasks:
            return 0
        completed = sum(1 for t in self.tasks if t.completed)
        return int(completed / len(self.tasks) * 100)

    @classmethod
    def from_dict(cls, data: dict) -> "Milestone":
        tasks = [Task.from_dict(t) for t in data.get("tasks", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            deadline=data.get("deadline", ""),
            tasks=tasks,
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "deadline": self.deadline,
            "tasks": [t.to_dict() for t in self.tasks],
        }


class Plan:
    """计划数据模型。"""

    def __init__(
        self,
        id: str,
        name: str,
        description: str = "",
        priority: str = "medium",
        milestones: Optional[List[Milestone]] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.id = id
        self.name = name
        self.description = description
        self.priority = priority
        self.milestones = milestones or []
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    @property
    def progress(self) -> int:
        if not self.milestones:
            return 0
        total = sum(len(m.tasks) for m in self.milestones)
        if total == 0:
            return 0
        completed = sum(
            sum(1 for t in m.tasks if t.completed) for m in self.milestones
        )
        return int(completed / total * 100)

    @property
    def total_tasks(self) -> int:
        return sum(len(m.tasks) for m in self.milestones)

    @property
    def completed_tasks(self) -> int:
        return sum(
            sum(1 for t in m.tasks if t.completed) for m in self.milestones
        )

    @classmethod
    def from_dict(cls, data: dict) -> "Plan":
        milestones = [Milestone.from_dict(m) for m in data.get("milestones", [])]
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            priority=data.get("priority", "medium"),
            milestones=milestones,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "priority": self.priority,
            "milestones": [m.to_dict() for m in self.milestones],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class PlanManager:
    """计划数据持久化管理。"""

    def __init__(self, plans_dir: Optional[Path] = None):
        self.plans_dir = plans_dir or DEFAULT_PLANS_DIR
        self.plans_dir.mkdir(parents=True, exist_ok=True)
        self._plans: Dict[str, Plan] = {}
        self._load_all()

    def create_plan(self, name: str) -> Plan:
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        plan = Plan(id=plan_id, name=name)
        self._plans[plan_id] = plan
        self.save_plan(plan)
        return plan

    def get_plan(self, plan_id: str) -> Optional[Plan]:
        return self._plans.get(plan_id)

    def delete_plan(self, plan_id: str) -> bool:
        if plan_id not in self._plans:
            return False
        del self._plans[plan_id]
        file_path = self._plan_file_path(plan_id)
        try:
            if file_path.exists():
                file_path.unlink()
        except OSError:
            pass
        return True

    def rename_plan(self, plan_id: str, new_name: str) -> bool:
        plan = self._plans.get(plan_id)
        if plan is None:
            return False
        plan.name = new_name
        plan.updated_at = datetime.now().isoformat()
        self.save_plan(plan)
        return True

    def all_plans(self) -> List[Plan]:
        return sorted(self._plans.values(), key=lambda p: p.updated_at, reverse=True)

    def save_plan(self, plan: Plan) -> None:
        plan.updated_at = datetime.now().isoformat()
        file_path = self._plan_file_path(plan.id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(plan.to_dict(), f, ensure_ascii=False, indent=2)
        except OSError as exc:
            logger.warning("保存计划失败: %s", exc)

    def _plan_file_path(self, plan_id: str) -> Path:
        return self.plans_dir / f"{plan_id}.json"

    def _load_all(self) -> None:
        if not self.plans_dir.exists():
            return
        for file_path in self.plans_dir.glob("*.json"):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                plan = Plan.from_dict(data)
                self._plans[plan.id] = plan
            except (json.JSONDecodeError, KeyError) as exc:
                logger.warning("加载计划失败 %s: %s", file_path.name, exc)


class PagePlan(QWidget):
    """计划编辑器页面。"""

    PRIORITY_LABELS = {"low": "低", "medium": "中", "high": "高"}

    def __init__(self, app_context, title: str = "计划编辑器", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.app_ctx = app_context
        self.title = title
        self.plan_manager = PlanManager()
        self._current_plan_id: Optional[str] = None
        self._init_ui()
        self._load_plans()
        self._apply_theme()
        self._connect_signals()

    def _init_ui(self) -> None:
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- 左侧计划列表 ---
        self.left_sidebar = QWidget()
        self.left_sidebar.setObjectName("planSidebar")
        self.left_sidebar.setFixedWidth(220)
        left_layout = QVBoxLayout(self.left_sidebar)
        left_layout.setContentsMargins(12, 12, 12, 12)
        left_layout.setSpacing(8)

        # 顶部工具栏
        header = QHBoxLayout()
        title = QLabel("计划编辑器")
        title.setObjectName("sidebarTitle")
        title_font = QFont()
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch()

        self.new_btn = QPushButton("+")
        self.new_btn.setFixedSize(28, 28)
        self.new_btn.setCursor(Qt.PointingHandCursor)
        self.new_btn.setToolTip("新建计划")
        self.new_btn.clicked.connect(self._on_new_plan)
        header.addWidget(self.new_btn)
        left_layout.addLayout(header)

        # 计划列表
        self.plan_list = QListWidget()
        self.plan_list.setObjectName("planList")
        self.plan_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.plan_list.customContextMenuRequested.connect(self._show_plan_menu)
        self.plan_list.itemClicked.connect(self._on_plan_selected)
        left_layout.addWidget(self.plan_list, 1)

        # 空状态
        self.empty_label = QLabel("暂无计划，点击右上角新建~")
        self.empty_label.setObjectName("planEmptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(self.empty_label)

        main_layout.addWidget(self.left_sidebar)

        # --- 右侧详情编辑区 ---
        self.right_panel = QWidget()
        self.right_panel.setObjectName("planPage")
        right_layout = QVBoxLayout(self.right_panel)
        right_layout.setContentsMargins(24, 24, 24, 24)
        right_layout.setSpacing(16)

        # 基础信息区
        info_card = self._create_section("基础信息")
        info_layout = info_card.layout()

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("计划名称:"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("输入计划名称...")
        name_row.addWidget(self.name_edit, 1)
        info_layout.addLayout(name_row)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("描述:"))
        self.desc_edit = QTextEdit()
        self.desc_edit.setPlaceholderText("描述这个计划的目标...")
        self.desc_edit.setMaximumHeight(60)
        desc_row.addWidget(self.desc_edit, 1)
        info_layout.addLayout(desc_row)

        priority_row = QHBoxLayout()
        priority_row.addWidget(QLabel("优先级:"))
        self.priority_combo = QComboBox()
        self.priority_combo.addItem("低", "low")
        self.priority_combo.addItem("中", "medium")
        self.priority_combo.addItem("高", "high")
        priority_row.addWidget(self.priority_combo)
        priority_row.addStretch()
        info_layout.addLayout(priority_row)

        right_layout.addWidget(info_card)

        # 里程碑与任务清单区
        milestone_card = self._create_section("里程碑与任务清单")
        milestone_layout = milestone_card.layout()

        self.milestone_tree = QTreeWidget()
        self.milestone_tree.setObjectName("planTree")
        self.milestone_tree.setHeaderHidden(True)
        self.milestone_tree.setColumnCount(1)
        self.milestone_tree.itemChanged.connect(self._on_tree_item_changed)
        milestone_layout.addWidget(self.milestone_tree)

        # 里程碑操作按钮
        ms_btn_row = QHBoxLayout()
        self.add_ms_btn = QPushButton("+ 添加里程碑")
        self.add_ms_btn.setObjectName("secondaryBtn")
        self.add_ms_btn.clicked.connect(self._on_add_milestone)
        ms_btn_row.addWidget(self.add_ms_btn)

        self.add_task_btn = QPushButton("+ 添加任务")
        self.add_task_btn.setObjectName("secondaryBtn")
        self.add_task_btn.clicked.connect(self._on_add_task)
        ms_btn_row.addWidget(self.add_task_btn)

        self.del_item_btn = QPushButton("删除选中")
        self.del_item_btn.setObjectName("dangerBtn")
        self.del_item_btn.clicked.connect(self._on_delete_tree_item)
        ms_btn_row.addWidget(self.del_item_btn)

        ms_btn_row.addStretch()
        milestone_layout.addLayout(ms_btn_row)

        right_layout.addWidget(milestone_card)

        # 总进度区
        progress_card = self._create_section("总进度")
        progress_layout = progress_card.layout()

        self.overall_progress = QProgressBar()
        self.overall_progress.setMinimum(0)
        self.overall_progress.setMaximum(100)
        self.overall_progress.setValue(0)
        self.overall_progress.setTextVisible(True)
        self.overall_progress.setFormat("%p%")
        progress_layout.addWidget(self.overall_progress)

        self.progress_label = QLabel("总进度: 0% (0/0 任务已完成)")
        self.progress_label.setObjectName("planProgressLabel")
        progress_layout.addWidget(self.progress_label)

        right_layout.addWidget(progress_card)

        # 操作按钮区
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self.save_btn = QPushButton("保存计划")
        self.save_btn.setObjectName("primaryBtn")
        self.save_btn.clicked.connect(self._on_save_plan)
        btn_row.addWidget(self.save_btn)

        self.delete_btn = QPushButton("删除计划")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.clicked.connect(self._on_delete_plan)
        btn_row.addWidget(self.delete_btn)

        right_layout.addLayout(btn_row)
        right_layout.addStretch()

        main_layout.addWidget(self.right_panel, 1)

    def _create_section(self, title: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("planSection")
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        return frame

    def _connect_signals(self) -> None:
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is not None:
            theme_engine.theme_changed.connect(self._on_theme_changed)

    def _load_plans(self) -> None:
        self.plan_list.clear()
        plans = self.plan_manager.all_plans()
        self.empty_label.setVisible(len(plans) == 0)

        for plan in plans:
            item = QListWidgetItem()
            progress = plan.progress
            item.setText(f"{plan.name} ({progress}%)")
            item.setData(Qt.UserRole, plan.id)
            self.plan_list.addItem(item)

        if plans:
            self.plan_list.setCurrentRow(0)
            self._on_plan_selected(self.plan_list.item(0))

    def _on_plan_selected(self, item: QListWidgetItem) -> None:
        if not item:
            return
        plan_id = item.data(Qt.UserRole)
        plan = self.plan_manager.get_plan(plan_id)
        if not plan:
            return

        self._current_plan_id = plan_id
        self.name_edit.setText(plan.name)
        self.desc_edit.setPlainText(plan.description)
        idx = self.priority_combo.findData(plan.priority)
        if idx >= 0:
            self.priority_combo.setCurrentIndex(idx)

        self._refresh_milestone_tree(plan)
        self._update_progress(plan)

    def _refresh_milestone_tree(self, plan: Plan) -> None:
        self.milestone_tree.clear()
        self.milestone_tree.setIconSize(QSize(_MILESTONE_ICON_SIZE, _MILESTONE_ICON_SIZE))
        for milestone in plan.milestones:
            ms_item = QTreeWidgetItem(self.milestone_tree)
            ic = _vector_icon(self.app_ctx, "bookmark", _MILESTONE_ICON_SIZE,
                              theme_color(self.app_ctx, "accent", "#FF6B9D"))
            if ic is not None:
                ms_item.setText(0, milestone.name)
                ms_item.setIcon(0, ic)
            else:
                ms_item.setText(0, f"📌 {milestone.name}")
            ms_item.setData(0, Qt.UserRole, ("milestone", milestone.id))
            ms_item.setFlags(ms_item.flags() | Qt.ItemIsEditable)

            for task in milestone.tasks:
                task_item = QTreeWidgetItem(ms_item)
                task_item.setText(0, task.name)
                task_item.setData(0, Qt.UserRole, ("task", task.id))
                task_item.setCheckState(0, Qt.Checked if task.completed else Qt.Unchecked)
                task_item.setFlags(task_item.flags() | Qt.ItemIsEditable)

            ms_item.setExpanded(True)

    def _update_progress(self, plan: Plan) -> None:
        progress = plan.progress
        self.overall_progress.setValue(progress)
        total = plan.total_tasks
        completed = plan.completed_tasks
        self.progress_label.setText(
            f"总进度: {progress}% ({completed}/{total} 任务已完成)"
        )

    def _on_tree_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        item_type, item_id = data
        if item_type == "task":
            # Update task completion state from checkbox
            checked = item.checkState(0) == Qt.Checked
            plan = self.plan_manager.get_plan(self._current_plan_id) if self._current_plan_id else None
            if plan:
                for ms in plan.milestones:
                    for task in ms.tasks:
                        if task.id == item_id:
                            task.completed = checked
                            break

    def _on_new_plan(self) -> None:
        name, ok = QInputDialog.getText(self, "新建计划", "计划名称:")
        if not ok or not name.strip():
            return
        plan = self.plan_manager.create_plan(name.strip())
        self._load_plans()
        for i in range(self.plan_list.count()):
            item = self.plan_list.item(i)
            if item.data(Qt.UserRole) == plan.id:
                self.plan_list.setCurrentItem(item)
                self._on_plan_selected(item)
                break

    def _on_add_milestone(self) -> None:
        if not self._current_plan_id:
            return
        name, ok = QInputDialog.getText(self, "添加里程碑", "里程碑名称:")
        if not ok or not name.strip():
            return
        plan = self.plan_manager.get_plan(self._current_plan_id)
        if not plan:
            return
        ms_id = f"ms_{uuid.uuid4().hex[:6]}"
        milestone = Milestone(id=ms_id, name=name.strip())
        plan.milestones.append(milestone)
        self._refresh_milestone_tree(plan)
        self._update_progress(plan)

    def _on_add_task(self) -> None:
        if not self._current_plan_id:
            return
        current_item = self.milestone_tree.currentItem()
        if not current_item:
            QMessageBox.information(self, "提示", "请先选择一个里程碑")
            return

        # Find parent milestone
        data = current_item.data(0, Qt.UserRole)
        if not data:
            return
        item_type, item_id = data

        plan = self.plan_manager.get_plan(self._current_plan_id)
        if not plan:
            return

        target_ms = None
        if item_type == "milestone":
            target_ms = next((m for m in plan.milestones if m.id == item_id), None)
        elif item_type == "task":
            # Find milestone containing this task
            for ms in plan.milestones:
                if any(t.id == item_id for t in ms.tasks):
                    target_ms = ms
                    break

        if not target_ms:
            return

        name, ok = QInputDialog.getText(self, "添加任务", "任务名称:")
        if not ok or not name.strip():
            return
        task_id = f"t_{uuid.uuid4().hex[:6]}"
        task = Task(id=task_id, name=name.strip())
        target_ms.tasks.append(task)
        self._refresh_milestone_tree(plan)
        self._update_progress(plan)

    def _on_delete_tree_item(self) -> None:
        current_item = self.milestone_tree.currentItem()
        if not current_item:
            return

        data = current_item.data(0, Qt.UserRole)
        if not data:
            return
        item_type, item_id = data

        plan = self.plan_manager.get_plan(self._current_plan_id) if self._current_plan_id else None
        if not plan:
            return

        if item_type == "milestone":
            plan.milestones = [m for m in plan.milestones if m.id != item_id]
        elif item_type == "task":
            for ms in plan.milestones:
                ms.tasks = [t for t in ms.tasks if t.id != item_id]

        self._refresh_milestone_tree(plan)
        self._update_progress(plan)

    def _on_save_plan(self) -> None:
        if not self._current_plan_id:
            return
        plan = self.plan_manager.get_plan(self._current_plan_id)
        if not plan:
            return

        plan.name = self.name_edit.text().strip()
        plan.description = self.desc_edit.toPlainText().strip()
        plan.priority = self.priority_combo.currentData()

        # Sync tree item text back to data
        root = self.milestone_tree.invisibleRootItem()
        for i in range(root.childCount()):
            ms_item = root.child(i)
            ms_data = ms_item.data(0, Qt.UserRole)
            if ms_data:
                _, ms_id = ms_data
                ms = next((m for m in plan.milestones if m.id == ms_id), None)
                if ms:
                    ms.name = ms_item.text(0).replace("📌 ", "", 1)
                    for j in range(ms_item.childCount()):
                        task_item = ms_item.child(j)
                        task_data = task_item.data(0, Qt.UserRole)
                        if task_data:
                            _, task_id = task_data
                            task = next((t for t in ms.tasks if t.id == task_id), None)
                            if task:
                                task.name = task_item.text(0)
                                task.completed = task_item.checkState(0) == Qt.Checked

        self.plan_manager.save_plan(plan)
        self._load_plans()
        QMessageBox.information(self, "成功", "计划已保存")

    def _on_delete_plan(self) -> None:
        if not self._current_plan_id:
            return
        plan = self.plan_manager.get_plan(self._current_plan_id)
        if not plan:
            return

        reply = QMessageBox.question(
            self, "删除计划",
            f"确定要删除计划 '{plan.name}' 吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.plan_manager.delete_plan(self._current_plan_id)
            self._current_plan_id = None
            self.name_edit.clear()
            self.desc_edit.clear()
            self.milestone_tree.clear()
            self.overall_progress.setValue(0)
            self.progress_label.setText("总进度: 0% (0/0 任务已完成)")
            self._load_plans()

    def _show_plan_menu(self, pos) -> None:
        item = self.plan_list.itemAt(pos)
        if not item:
            return
        plan_id = item.data(Qt.UserRole)
        plan = self.plan_manager.get_plan(plan_id)
        if not plan:
            return

        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        action = menu.exec_(self.plan_list.mapToGlobal(pos))

        if action == rename_action:
            self._rename_plan(plan_id)
        elif action == delete_action:
            self._current_plan_id = plan_id
            self._on_delete_plan()

    def _rename_plan(self, plan_id: str) -> None:
        plan = self.plan_manager.get_plan(plan_id)
        if not plan:
            return
        name, ok = QInputDialog.getText(self, "重命名计划", "新名称:", text=plan.name)
        if ok and name.strip():
            self.plan_manager.rename_plan(plan_id, name.strip())
            self._load_plans()

    def _apply_theme(self) -> None:
        theme_engine = getattr(self.app_ctx, "theme_engine", None)
        if theme_engine is None:
            return

        bg = theme_engine.get_color("bg", "#FFF5F5")
        text = theme_engine.get_color("text", "#5D4037")
        primary = theme_engine.get_color("primary", "#FF6B9D")
        secondary = theme_engine.get_color("text_secondary", "#888888")
        border = theme_engine.get_color("border", "#FFE4EC")
        card_bg = theme_engine.get_color("bg_card", "#FFFFFF")

        self.setStyleSheet(f"""
            QWidget#planPage {{
                background: {bg};
            }}
            /* v2.1(UI-Fix-0912): 显式兜住本页 QLabel 颜色 —— 页面自有 setStyleSheet
               会遮蔽应用级 QSS 的继承,若主题加载失败/明暗错配则本页文字失去颜色。
               更具体的 ID 规则(如 QLabel#roleHint)按特异性胜出,不受影响。 */
            QLabel {{ color: {text}; }}
            QWidget#planSidebar {{
                background: {card_bg};
                border-right: 1px solid {border};
            }}
            QListWidget#planList {{
                background: transparent;
                border: none;
                outline: none;
                color: {text};
            }}
            QListWidget#planList::item {{
                padding: 8px 12px;
                border-radius: 8px;
            }}
            QListWidget#planList::item:selected {{
                background: {primary}22;
                color: {primary};
                font-weight: 500;
            }}
            QListWidget#planList::item:hover {{
                background: {primary}11;
            }}
            QFrame#planSection {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 12px;
            }}
            QLabel#planEmptyState {{
                color: {secondary};
                font-size: 12px;
            }}
            QLabel#planProgressLabel {{
                color: {secondary};
                font-size: 12px;
            }}
            QTreeWidget#planTree {{
                background: {card_bg};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 8px;
            }}
            QTreeWidget#planTree::item {{
                padding: 4px 8px;
            }}
            QProgressBar {{
                border: 1px solid {border};
                border-radius: 6px;
                text-align: center;
                background: {bg};
            }}
            QProgressBar::chunk {{
                background: {primary};
                border-radius: 6px;
            }}
        """)

    def _on_theme_changed(self, theme_name: str) -> None:
        self._apply_theme()
