SET NAMES utf8mb4;
CREATE DATABASE IF NOT EXISTS meta DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
GRANT ALL PRIVILEGES ON meta.* TO 'atguigu'@'%';

USE meta;

CREATE TABLE semantic_model_version (
    version_id VARCHAR(64) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    content_hash VARCHAR(64) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at DATETIME NULL,
    description TEXT NULL,
    active_version_guard INT GENERATED ALWAYS AS (
        CASE WHEN status = 'active' THEN 1 ELSE NULL END
    ) STORED,
    PRIMARY KEY (version_id),
    CONSTRAINT ck_semantic_model_version_status
        CHECK (status IN ('draft', 'active', 'archived')),
    CONSTRAINT uq_semantic_model_one_active UNIQUE (active_version_guard)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE semantic_model_current (
    singleton_id INT NOT NULL,
    version_id VARCHAR(64) NULL,
    PRIMARY KEY (singleton_id),
    CONSTRAINT ck_semantic_model_current_singleton CHECK (singleton_id = 1),
    CONSTRAINT fk_semantic_model_current_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO semantic_model_current (singleton_id, version_id) VALUES (1, NULL);

CREATE TABLE table_info (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL COMMENT '表编号',
    name VARCHAR(128) NULL COMMENT '表名称',
    role VARCHAR(32) NULL COMMENT '表类型(fact/dim)',
    description TEXT NULL COMMENT '表描述',
    PRIMARY KEY (version_id, id),
    CONSTRAINT uq_table_info_version_name UNIQUE (version_id, name),
    CONSTRAINT fk_table_info_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE column_info (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL COMMENT '列编号',
    name VARCHAR(128) NULL COMMENT '列名称',
    type VARCHAR(64) NULL COMMENT '数据类型',
    role VARCHAR(32) NULL COMMENT '列类型(primary_key,foreign_key,measure,dimension)',
    examples JSON NULL COMMENT '数据示例',
    description TEXT NULL COMMENT '列描述',
    alias JSON NULL COMMENT '列别名',
    table_id VARCHAR(64) NOT NULL COMMENT '所属表编号',
    PRIMARY KEY (version_id, id),
    CONSTRAINT fk_column_info_version_table FOREIGN KEY (version_id, table_id)
        REFERENCES table_info (version_id, id),
    CONSTRAINT fk_column_info_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE time_dimension (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    year_field VARCHAR(128) NOT NULL,
    quarter_field VARCHAR(128) NOT NULL,
    month_field VARCHAR(128) NOT NULL,
    day_field VARCHAR(128) NOT NULL,
    date_key_field VARCHAR(128) NOT NULL,
    supported_grains JSON NOT NULL,
    month_filter_requires_year BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (version_id, id),
    CONSTRAINT fk_time_dimension_version_table FOREIGN KEY (version_id, table_name)
        REFERENCES table_info (version_id, id),
    CONSTRAINT fk_time_dimension_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE dataset (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL,
    table_name VARCHAR(128) NOT NULL,
    grain VARCHAR(64) NOT NULL,
    primary_key VARCHAR(128) NOT NULL,
    time_dimension_id VARCHAR(64) NOT NULL,
    PRIMARY KEY (version_id, id),
    CONSTRAINT fk_dataset_version_table FOREIGN KEY (version_id, table_name)
        REFERENCES table_info (version_id, id),
    CONSTRAINT fk_dataset_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id),
    CONSTRAINT fk_dataset_version_time_dimension FOREIGN KEY (version_id, time_dimension_id)
        REFERENCES time_dimension (version_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE dimension_info (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    table_id VARCHAR(64) NOT NULL,
    column_id VARCHAR(64) NOT NULL,
    aliases JSON NOT NULL,
    PRIMARY KEY (version_id, id),
    CONSTRAINT fk_dimension_version_table FOREIGN KEY (version_id, table_id)
        REFERENCES table_info (version_id, id),
    CONSTRAINT fk_dimension_version_column FOREIGN KEY (version_id, column_id)
        REFERENCES column_info (version_id, id),
    CONSTRAINT fk_dimension_info_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE metric_info (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL COMMENT '指标编码',
    name VARCHAR(128) NULL COMMENT '指标名称',
    description TEXT NULL COMMENT '指标描述',
    relevant_columns JSON NULL COMMENT '关联的列',
    alias JSON NULL COMMENT '指标别名',
    metric_type VARCHAR(32) NULL COMMENT '指标类型',
    expression TEXT NULL COMMENT '指标表达式',
    numerator VARCHAR(64) NULL COMMENT '比例指标分子',
    denominator VARCHAR(64) NULL COMMENT '比例指标分母',
    base_dataset VARCHAR(64) NULL COMMENT '基础数据集',
    status VARCHAR(32) NULL COMMENT '指标状态',
    grain VARCHAR(64) NULL COMMENT '统计粒度',
    period VARCHAR(64) NULL COMMENT '统计周期',
    business_scope TEXT NULL COMMENT '业务限定',
    aggregation VARCHAR(64) NULL COMMENT '聚合方式',
    stage VARCHAR(32) NULL COMMENT '计算阶段',
    allowed_dimensions JSON NULL COMMENT '允许维度',
    expression_ast JSON NULL COMMENT '结构化表达式树',
    PRIMARY KEY (version_id, id),
    CONSTRAINT fk_metric_version_dataset FOREIGN KEY (version_id, base_dataset)
        REFERENCES dataset (version_id, id),
    CONSTRAINT fk_metric_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id),
    CONSTRAINT fk_metric_version_numerator FOREIGN KEY (version_id, numerator)
        REFERENCES metric_info (version_id, id),
    CONSTRAINT fk_metric_version_denominator FOREIGN KEY (version_id, denominator)
        REFERENCES metric_info (version_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE relationship (
    version_id VARCHAR(64) NOT NULL,
    id VARCHAR(64) NOT NULL,
    source VARCHAR(128) NOT NULL,
    target VARCHAR(128) NOT NULL,
    cardinality VARCHAR(32) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (version_id, id),
    CONSTRAINT fk_relationship_version FOREIGN KEY (version_id)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE column_metric (
    version_id VARCHAR(64) NOT NULL,
    column_id VARCHAR(64) NOT NULL COMMENT '列编号',
    metric_id VARCHAR(64) NOT NULL COMMENT '指标编号',
    PRIMARY KEY (version_id, column_id, metric_id),
    CONSTRAINT fk_column_metric_version_column FOREIGN KEY (version_id, column_id)
        REFERENCES column_info (version_id, id),
    CONSTRAINT fk_column_metric_version_metric FOREIGN KEY (version_id, metric_id)
        REFERENCES metric_info (version_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE metric_dependency (
    version_id VARCHAR(64) NOT NULL,
    metric_id VARCHAR(64) NOT NULL,
    depends_on_metric_id VARCHAR(64) NOT NULL,
    dependency_order INT NOT NULL DEFAULT 0,
    PRIMARY KEY (version_id, metric_id, depends_on_metric_id, dependency_order),
    CONSTRAINT fk_metric_dependency_version_metric FOREIGN KEY (version_id, metric_id)
        REFERENCES metric_info (version_id, id),
    CONSTRAINT fk_metric_dependency_version_target FOREIGN KEY (version_id, depends_on_metric_id)
        REFERENCES metric_info (version_id, id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
CREATE TABLE semantic_index_verification (
    id BIGINT NOT NULL AUTO_INCREMENT,
    version_id VARCHAR(128) NOT NULL,
    content_hash VARCHAR(128) NOT NULL,
    config_hash VARCHAR(128) NOT NULL,
    target VARCHAR(32) NOT NULL,
    es_index_name VARCHAR(255) NOT NULL,
    qdrant_collection_name VARCHAR(255) NOT NULL,
    manifest_hash VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    verified_at DATETIME NOT NULL,
    expires_at DATETIME NULL,
    details TEXT NOT NULL,
    PRIMARY KEY (id),
    INDEX ix_semantic_index_verification_version (version_id),
    INDEX ix_semantic_index_verification_lookup (version_id, content_hash, config_hash, target, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE application_session (
    session_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    original_query TEXT NOT NULL,
    current_query TEXT NOT NULL,
    clarification_id VARCHAR(64) NULL,
    turn_id VARCHAR(64) NOT NULL,
    turn_number INT NOT NULL,
    state_version INT NOT NULL,
    semantic_model_version VARCHAR(64) NOT NULL,
    pending_fields TEXT NULL,
    query_intent_snapshot TEXT NULL,
    terminal_status VARCHAR(32) NULL,
    execution_marker VARCHAR(32) NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    completed_at DATETIME NULL,
    PRIMARY KEY (session_id),
    INDEX ix_application_session_expires (expires_at),
    INDEX ix_application_session_clarification (session_id, clarification_id, state_version),
    CONSTRAINT fk_application_session_version FOREIGN KEY (semantic_model_version)
        REFERENCES semantic_model_version (version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
