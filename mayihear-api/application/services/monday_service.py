from infrastructure.monday_client import (
    get_boards, get_items, get_columns, get_board_items,
    get_board_details, post_update, update_column, update_long_text_column
)
from infrastructure.utilities import secret_manager
from domain.models.input.monday_publish_request import MondayPublishRequest
from domain.models.output.monday_result import BoardInfo, ItemInfo, ColumnInfo, BoardDetails, GroupInfo, MondayPublishResult


class MondayService:

    def list_boards(self) -> list:
        return [BoardInfo(id=str(b["id"]), name=b["name"]) for b in get_boards()]

    def list_items(self, board_id: str) -> list:
        return [ItemInfo(id=str(i["id"]), name=i["name"]) for i in get_items(board_id)]

    def list_columns(self, board_id: str) -> list:
        return [ColumnInfo(id=c["id"], title=c["title"], type=c["type"]) for c in get_columns(board_id)]

    def list_projects(self) -> list:
        board_id = secret_manager.get_monday_board_id()
        return [ItemInfo(id=str(i["id"]), name=i["name"]) for i in get_board_items(board_id)]

    def publish(self, request: MondayPublishRequest) -> MondayPublishResult:
        try:
            if request.column_id:
                uid = update_column(request.board_id, request.item_id, request.column_id, request.content)
            else:
                uid = post_update(request.item_id, request.content)
            return MondayPublishResult(ok=True, update_id=uid)
        except Exception as e:
            return MondayPublishResult(ok=False, error=str(e))

    def get_board_details(self, board_id: str) -> BoardDetails:
        raw = get_board_details(board_id)
        return BoardDetails(
            id=board_id,
            name=raw.get("name", ""),
            description=raw.get("description"),
            items_count=raw.get("items_count"),
            groups=[GroupInfo(id=g["id"], title=g["title"], color=g.get("color")) for g in raw.get("groups", [])],
            columns=[ColumnInfo(id=c["id"], title=c["title"], type=c["type"]) for c in raw.get("columns", [])],
        )

    def update_monday_settings(self, token: str, board_id: str = None, column_id: str = None):
        secret_manager.set_override('MONDAY_API_TOKEN', token)
        if board_id:
            secret_manager.set_override('MONDAY_BOARD_ID', board_id)
        if column_id:
            secret_manager.set_override('MONDAY_COLUMN_ID', column_id)

    def publish_acta(self, item_id: str, content: str) -> MondayPublishResult:
        try:
            board_id  = secret_manager.get_monday_board_id()
            column_id = secret_manager.get_monday_column_id()
            uid = update_long_text_column(board_id, item_id, column_id, content)
            return MondayPublishResult(ok=True, update_id=uid)
        except Exception as e:
            return MondayPublishResult(ok=False, error=str(e))
