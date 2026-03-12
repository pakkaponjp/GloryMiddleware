# -*- coding: utf-8 -*-
"""
Migration: Add FlowCo CloseShift audit fields + gas.station.shift.audit.line model

Place this file in:
    gas_station_cash/migrations/<version>/post-migrate.py
  or run manually via odoo shell:
    exec(open('/path/to/migration_flowco_audit.py').read())
"""

import logging
_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Called automatically by Odoo migration framework."""
    _add_flowco_columns(cr)
    _create_audit_line_table(cr)


def _add_flowco_columns(cr):
    """Add FlowCo metadata columns to gas_station_shift_audit."""
    columns = [
        ("flowco_shift_number", "VARCHAR"),
        ("flowco_pos_id",       "INTEGER DEFAULT 0"),
        ("flowco_timestamp",    "TIMESTAMP WITHOUT TIME ZONE"),
        ("pos_data_raw",        "TEXT"),
    ]
    for col, dtype in columns:
        cr.execute("""
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'gas_station_shift_audit'
              AND column_name = %s
        """, (col,))
        if not cr.fetchone():
            cr.execute(
                f"ALTER TABLE gas_station_shift_audit ADD COLUMN {col} {dtype}"
            )
            _logger.info("Added column gas_station_shift_audit.%s", col)
        else:
            _logger.info("Column gas_station_shift_audit.%s already exists, skipping", col)


def _create_audit_line_table(cr):
    """Create gas_station_shift_audit_line table if not exists."""
    cr.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'gas_station_shift_audit_line'
    """)
    if cr.fetchone():
        _logger.info("Table gas_station_shift_audit_line already exists, skipping")
        return

    cr.execute("""
        CREATE TABLE gas_station_shift_audit_line (
            id                  SERIAL PRIMARY KEY,
            audit_id            INTEGER NOT NULL
                                    REFERENCES gas_station_shift_audit(id)
                                    ON DELETE CASCADE,
            staff_external_id   VARCHAR NOT NULL DEFAULT '',
            staff_record_id     INTEGER,          -- gas_station_staff.id (nullable)
            saleamt_fuel        NUMERIC(16,2) NOT NULL DEFAULT 0,
            dropamt_fuel        NUMERIC(16,2) NOT NULL DEFAULT 0,
            saleamt_lube        NUMERIC(16,2) NOT NULL DEFAULT 0,
            dropamt_lube        NUMERIC(16,2) NOT NULL DEFAULT 0,
            pos_line_status     VARCHAR,
            -- computed helpers (stored)
            is_error            BOOLEAN NOT NULL DEFAULT FALSE,
            fuel_diff           NUMERIC(16,2) NOT NULL DEFAULT 0,
            lube_diff           NUMERIC(16,2) NOT NULL DEFAULT 0,
            -- Odoo standard columns
            currency_id         INTEGER,
            create_uid          INTEGER,
            write_uid           INTEGER,
            create_date         TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
            write_date          TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW()
        )
    """)
    cr.execute("""
        CREATE INDEX idx_audit_line_audit_id
            ON gas_station_shift_audit_line(audit_id)
    """)
    cr.execute("""
        CREATE INDEX idx_audit_line_staff_ext
            ON gas_station_shift_audit_line(staff_external_id)
    """)
    _logger.info("Created table gas_station_shift_audit_line")