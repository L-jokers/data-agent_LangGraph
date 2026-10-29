from dataclasses import asdict

from app.entities.relationship_info import RelationshipInfo
from app.models.relationship_info_mysql import RelationshipInfoMySQL


class RelationshipInfoMapper:
    @staticmethod
    def to_model(entity: RelationshipInfo) -> RelationshipInfoMySQL:
        return RelationshipInfoMySQL(**asdict(entity))
