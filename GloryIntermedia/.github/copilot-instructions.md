# AI Coding Assistant Instructions for GloryIntermedia Gas Station ERP

## Project Overview
This is an Odoo-based ERP system for gas station cash management, integrating Glory FCC cash recyclers with POS systems via TCP/JSON and SOAP APIs.

## Architecture
- **Core Modules**: `gas_station_cash` (cash deposits), `gas_station_erp_mini` (staff), `glory_fcc_integration` (hardware), `pos_tcp_connector` (POS comms)
- **Data Flow**: Cash deposits → POS validation → Glory FCC processing → Database audit trail
- **Communication**: TCP JSON to POS, SOAP to Glory hardware, Odoo bus for real-time UI updates

## Key Patterns

### Models
- Inherit `mail.thread` for audit trails: `class MyModel(models.Model): _inherit = ["mail.thread", "mail.activity.mixin"]`
- Use mixins for cross-cutting concerns: `PosConnectorMixin` for TCP communication
- State machines: `draft` → `confirmed` → `audited` for deposits
- POS status tracking: `pos_status` field with values `na`, `queued`, `failed`, `ok`

### Controllers
- JSON responses: `return request.make_response(json.dumps(payload), headers=[("Content-Type", "application/json")])`
- UUID for request tracking: `request_id = uuid.uuid4().hex`
- Async processing for external calls: Use threading for non-blocking POS communication

### Frontend (Odoo OWL)
- Register actions: `registry.category("actions").add("module.action_name", ComponentClass)`
- Bus channels: `(dbname, "module:terminal_id")` for real-time updates
- Badge widgets: `decoration-success/warning/danger` for status indicators

### Communication Patterns
- TCP JSON client: Send JSON line, receive JSON response (see `pos_tcp_client.py`)
- SOAP integration: Zeep library for Glory FCC status requests
- Pending transaction handling: Queue POS-related deposits before CloseShift

## Developer Workflows

### Running the System
```bash
# Start Odoo server
python3 odoo/odoo-bin -c odoo.conf

# Update modules
python3 odoo/odoo-bin -c odoo.conf --update all --init all
```

### POS Configuration
- Set `pos_vendor` in `odoo.conf` (firstpro/flowco)
- TCP settings: `pos_firstpro_host`, `pos_firstpro_port`
- Use `PosConnectorMixin` for reliable TCP communication with retry logic

### Deposit Types
Primary types: `oil`, `engine_oil`, `rental`, `coffee_shop`, `convenient_store`, `deposit_cash`, `exchange_cash`
- Oil/engine_oil always POS-related
- Check `product_id.is_pos_related` or deposit's `is_pos_related` flag

### Error Handling
- Log with `_logger.info/warning/error`
- Mark POS commands as `failed` with error codes and messages
- Use try/except with specific exception types (socket.timeout, json.JSONDecodeError)

## Code Examples

### Creating POS Command
```python
cmd = self.env["gas.station.pos_command"].create({
    "action": "close_shift",
    "request_id": uuid.uuid4().hex,
    "pos_terminal_id": "TERM-01",
    "status": "processing"
})
cmd.push_overlay()  # Real-time UI update
```

### TCP Communication
```python
config = self._get_pos_config()
client = PosTcpClient(config['host'], config['port'])
response = client.send_message({"action": "CloseShift", "staff_id": staff_id})
```

### Model with POS Integration
```python
class MyModel(models.Model):
    _inherit = ["mail.thread"]
    
    pos_status = fields.Selection([
        ('na', 'N/A'), ('queued', 'Queued'), ('failed', 'Failed'), ('ok', 'OK')
    ], default='na')
    pos_transaction_id = fields.Char(index=True)
    
    def send_to_pos(self):
        # Use PosConnectorMixin methods
        pass
```

## File Organization
- `models/`: Business logic and data structures
- `controllers/`: HTTP endpoints for external integrations
- `services/`: TCP/SOAP clients
- `views/`: XML forms and trees
- `static/src/js/`: OWL components and screens
- `static/src/scss/`: Styling for cash recycler interface

## Integration Points
- **Glory FCC**: SOAP API at configurable IP/port for cash recycler status
- **POS Systems**: TCP JSON for transaction sync and shift management
- **Odoo Bus**: Real-time UI updates for command overlays
- **External APIs**: JSON samples in `_check_API.json`, SOAP in `_check_SOAP.xml`