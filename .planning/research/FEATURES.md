# Feature Research

**Domain:** MCP Server for Django frameworks
**Researched:** 2026-04-03
**Confidence:** HIGH

## Source

- `django-mcp-server` — https://github.com/gts360/django-mcp-server (Apache-2.0)
- Key files: `mcp_server/djangomcp.py`, `mcp_server/views.py`, `mcp_server/query_tool.py`
- Architecture: `DjangoMCP(FastMCP)` — WSGI bridge + session manager composition

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = broken MCP endpoint.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| HTTP MCP endpoint in Django | Standard entry point for MCP clients (Claude Desktop, ADK) | LOW | `MCPServerStreamableHttpView` (DRF APIView) + `async_to_sync` bridge |
| Session state persistence across requests | MCP clients reconnect; scoping must survive | MEDIUM | `DjangoMCP.handle_django_request()` reads/writes `Mcp-Session-Id` header, delegates to Django `SessionStore` |
| `async_to_sync` instead of `asyncio.run()` | `asyncio.run()` creates/destroys event loop per request — wipes session state | MEDIUM | `async_to_sync(_call_starlette_handler)(request, session_manager)` — loop is reused, not destroyed |
| ASGI scope built from Django request | FastMCP needs Starlette ASGI scope; Django has WSGI | LOW | `_call_starlette_handler()` constructs `Scope` dict with scheme, host, port, headers |
| DRF-level auth on the MCP view | Gate MCP endpoint before hitting FastMCP internals | LOW | `MCPServerStreamableHttpView` uses `authentication_classes` from settings; Nautobot has no DRF |
| `MCPSessionState` abstraction | Session state must be readable/writable by session tools | LOW | Thin wrapper: `from_session(dict)` + `apply_to_session(dict)` — Nautobot's is equivalent |
| StreamableHTTPSessionManager.run() context manager | FastMCP requires a running context to access session | LOW | `async with session_manager.run():` — holds session context for FastMCP |
| `Mcp-Session-Id` in response headers | Client must receive session key to make subsequent requests | LOW | `result.headers["Mcp-Session-Id"] = request.session.session_key` |

### Differentiators (Competitive Advantage)

Features that set the product apart. Not required, but valuable.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Declarative tool registration via metaclass** | Auto-publish every public method as an MCP tool — zero boilerplate | MEDIUM | `MCPToolset` + `ToolsetMeta` auto-registers subclasses; Nautobot uses explicit `register_mcp_tool()` — both valid |
| **Auto-generate JSON Schema from Django model fields** | 2-line model exposure vs hand-written schema per tool | HIGH | `generate_json_schema()` maps Django field types to BSON types, infers `required`, choices enums, FK refs, help_text |
| **MongoDB aggregation pipeline DSL for querying** | Rich query language for AI agents without hand-rolling tools | HIGH | `$match`, `$lookup`, `$sort`, `$limit`, `$group` → Django ORM; Nautobot doesn't need this |
| **DRF view → MCP tool decorator** | One decorator converts Create/List/Update/Delete APIViews | MEDIUM | `@drf_publish_create_mcp_tool`, `_DRFRequestWrapper` bridges MCP call to DRF view; Nautobot has no DRF |
| **Progressive disclosure via session state** | Manage tool visibility per-conversation without admin UI | MEDIUM | Nautobot has this via `MCPSessionState` + `mcp_enable_tools`/`disable_tools`/`list_tools` |
| **Nautobot object-level `.restrict()` permissions** | Per-call ORM-level security enforcement | LOW | Nautobot-specific; django-mcp-server has no equivalent |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Redis session backend for MCP | Shared sessions across multiple Django workers | Over-engineering for v1; in-memory FastMCP sessions work for single Docker worker | Document tradeoff; upgrade to Django sessions only if multi-process deployment is needed |
| Write tools (create/update/delete) | Completeness — agents want to make changes | Permission surface widens; transactional safety, rollback, idempotency needed | Defer to v2; agents use Nautobot REST API directly for writes |
| Real-time streaming (SSE) | Immediate tool results feel modern | Buffer management; connection complexity | Cursor pagination handles memory |
| Separate ASGI worker process for MCP | Isolates MCP runtime from Django | Two processes, two configs, network hop | Embedded in Django process (current) |

---

## Feature Extraction: django-mcp-server Patterns

### 1. DjangoMCP Class — Extends FastMCP

**File:** `mcp_server/djangomcp.py`

`DjangoMCP` subclasses `FastMCP` to:
1. Compose its own `StreamableHTTPSessionManager` with `stateless=True` (sessions delegated out, not FastMCP in-memory)
2. Inject Django's `SessionStore` for real persistence
3. Provide `handle_django_request()` as the DRF view → MCP entry point
4. Expose `register_mcptoolset()` for declarative tool registration

```python
class DjangoMCP(FastMCP):
    def __init__(self, name=None, instructions=None, stateless=False):
        super().__init__(name or "django_mcp_server", instructions)
        self.stateless = stateless
        engine = import_module(settings.SESSION_ENGINE)
        self.SessionStore = engine.SessionStore  # ← Django session backend injected

        # Optionally auto-publish a get_server_instructions tool
        if getattr(settings, "DJANGO_MCP_GET_SERVER_INSTRUCTIONS_TOOL", True):
            async def _get_server_instructions():
                return self._mcp_server.instructions or ""
            self._tool_manager.add_tool(fn=_get_server_instructions, ...)

    @property
    def session_manager(self) -> StreamableHTTPSessionManager:
        return StreamableHTTPSessionManager(
            app=self._mcp_server,
            event_store=self._event_store,
            json_response=True,
            stateless=True,  # Sessions delegated to Django; NOT FastMCP in-memory
        )

    def handle_django_request(self, request):
        """Entry point called by MCPServerStreamableHttpView."""
        if not self.stateless:
            session_key = request.headers.get("Mcp-Session-Id")
            if session_key:
                session = self.SessionStore(session_key)
                if session.exists(session_key):
                    request.session = session
                else:
                    return HttpResponse(status=404, content="Session not found")
            elif request.data.get("method") == "initialize":
                request.session = self.SessionStore()  # create new session for handshake
            else:
                return HttpResponse(status=400, content="Session required for stateful server")

        result = async_to_sync(_call_starlette_handler)(request, self.session_manager)

        # Persist session + return Mcp-Session-Id header to client
        if not self.stateless and hasattr(request, "session"):
            request.session.save()
            result.headers["Mcp-Session-Id"] = request.session.session_key
            delattr(request, "session")

        return result
```

**Key insight:** `stateless=True` in FastMCP means "don't store sessions in FastMCP's in-memory dict." The actual session data lives in Django's session backend, keyed by `Mcp-Session-Id`. Nautobot does NOT need to adopt this — Docker single-process means in-memory FastMCP sessions are fine once `async_to_sync` is fixed.

**What Nautobot needs from this pattern:**
- `async_to_sync` bridge (not `asyncio.run()`) — **critical fix**
- `StreamableHTTPSessionManager.run()` context manager wrapping `handle_request` — **needed for session to live**
- Session dict attached to Django request object, then passed to `_call_starlette_handler` — **how FastMCP accesses it**
- `Mcp-Session-Id` in response headers — **already done in current code**

---

### 2. Session Management — Mcp-Session-Id Flow

**File:** `mcp_server/djangomcp.py`, `MCPServerStreamableHttpView`

```
Client → POST /mcp  (header: Mcp-Session-Id: <key>)
       → MCPServerStreamableHttpView.get() / .post()
       → DjangoMCP.handle_django_request()
              ├── Read "Mcp-Session-Id" header → load Django SessionStore(session_key)
              ├── Attach session to request.session
              ├── async_to_sync(_call_starlette_handler)(request, session_manager)
              │       └── async with session_manager.run():
              │               └── await session_manager.handle_request(scope, receive, send)
              │                       └── FastMCP MCP protocol handlers
              │                               └── MCP tool execution reads/writes session dict
              ├── session.save()  [persist to Django backend]
              └── Response header: Mcp-Session-Id = session.session_key
       ← Client stores Mcp-Session-Id for next request
```

**django-mcp-server session lifecycle (non-stateless mode):**

```python
# In DjangoMCP.handle_django_request():
session_key = request.headers.get("Mcp-Session-Id")
if session_key:
    session = self.SessionStore(session_key)
    if session.exists(session_key):
        request.session = session  # attach to Django request
    else:
        return HttpResponse(status=404, content="Session not found")
elif request.data.get("method") == "initialize":
    request.session = self.SessionStore()  # new session for MCP handshake
else:
    return HttpResponse(status=400, content="Session required for stateful server")

# ... FastMCP runs here, session dict is live in session_manager.run() ...

if hasattr(request, "session"):
    request.session.save()  # persist to DB/cookie backend
    result.headers["Mcp-Session-Id"] = request.session.session_key
```

**How FastMCP reads/writes session:** Inside `_call_starlette_handler`, the `StreamableHTTPSessionManager` manages the session lifecycle. The session dict it uses is the same object as `request.session` (set by `DjangoMCP`). Writes made by FastMCP during `handle_request` are persisted when `session.save()` is called.

**Nautobot's current broken approach:** FastMCP's `StreamableHTTPSessionManager` with `stateless_http=False` stores sessions in an **in-memory dict** that is destroyed on every `asyncio.run()` call. `Mcp-Session-Id` is sent/received but FastMCP's session lookup happens in a loop that no longer exists.

**The fix:** Replace `asyncio.run()` with `async_to_sync`. Do NOT adopt Django session delegation — Nautobot's Docker single-process means in-memory FastMCP sessions are fine once the loop lifetime is fixed.

---

### 3. Tool Registration — MCPToolset (Metaclass) vs Manual Singleton

**File:** `mcp_server/djangomcp.py`

**Metaclass approach (django-mcp-server):**

```python
class ToolsetMeta(type):
    registry = {}

    def __init__(cls, name, bases, namespace):
        super().__init__(name, bases, namespace)
        if name != "MCPToolset" and issubclass(cls, MCPToolset):
            ToolsetMeta.registry[name] = cls  # auto-register on class definition

class MCPToolset(metaclass=ToolsetMeta):
    mcp_server: DjangoMCP = None

    def __init__(self, context=None, request=None):
        self.context = context
        self.request = request
        if self.mcp_server is None:
            self.mcp_server = global_mcp_server

    def _add_tools_to(self, tool_manager):
        ret = []
        for name, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if not callable(method) or name.startswith("_"):
                continue
            tool = tool_manager.add_tool(sync_to_async(method))
            tool.context_kwarg = tool.context_kwarg or "_context"
            tool.fn = _ToolsetMethodCaller(self.__class__, name, tool.context_kwarg, forward_context)
            ret.append(tool)
        return ret

# init() registers all MCPToolset subclasses:
def init():
    for _name, cls in ToolsetMeta.iter_all():
        if cls.mcp_server is None:
            cls.mcp_server = global_mcp_server
    for _name, cls in ToolsetMeta.iter_all():
        cls.mcp_server.register_mcptoolset(cls())
```

**Usage — every public method becomes an MCP tool automatically:**

```python
class MyAppTools(MCPToolset):
    def list_devices(self, region: str) -> list[dict]:
        """List devices in a region."""
        return Device.objects.filter(region=region)
    def get_device(self, id: str) -> dict:
        return Device.objects.get(pk=id)
# Both methods are automatically exposed as MCP tools — zero per-method registration.
```

**nautobot-app-mcp-server's current manual approach:**

```python
# In session_tools.py — explicit per-tool registration:
register_mcp_tool(
    name="mcp_enable_tools",
    func=_mcp_enable_tools_impl,
    description="...",
    input_schema={...},
    tier="core",
)
```

**Assessment:** Metaclass is more ergonomic for large tool sets (50+). Nautobot's explicit `register_mcp_tool()` is explicit, type-safe, and sufficient for the current ~10 core tools. Switching to metaclass is a larger refactor with diminishing returns unless tools grow significantly.

**What Nautobot should borrow from this pattern:**
- `_ToolsetMethodCaller` — bridges FastMCP tool call → class method, passing `context` and `request`
- `sync_to_async` wrapper — ensures sync ORM methods run correctly in FastMCP's async context
- `django_request_ctx` context var — stores Django request in a context variable so tools can access `request.user` without explicit passing

---

### 4. ModelQueryToolset — Auto JSON Schema Generation

**File:** `mcp_server/query_tool.py`

`generate_json_schema()` introspects Django model fields and produces a MongoDB-style `$jsonSchema`:

```python
def generate_json_schema(model, fields=None, exclude=None):
    type_mapping = {
        models.CharField: "string",
        models.TextField: "string",
        models.IntegerField: "int",
        models.BooleanField: "bool",
        models.DateTimeField: "date",
        models.JSONField: "object",
        models.ForeignKey: "objectId",  # special case
        models.AutoField: "int",
        models.BigAutoField: "long",
        # ...
    }

    schema = {
        "description": (model.__doc__ or "").strip(),
        "$jsonSchema": {"bsonType": "object", "properties": {}, "required": []}
    }

    for field in model._meta.get_fields():
        if not field.concrete:
            continue
        if fields and field.name not in fields:
            continue
        if exclude and field.name in exclude:
            continue

        prop = {}

        if isinstance(field, models.ForeignKey):
            prop["bsonType"] = "objectId"
            prop["description"] = f"Reference to {field.related_model.__name__}"
            prop["ref"] = field.related_model.__name__
        else:
            for django_type, bson_type in type_mapping.items():
                if isinstance(field, django_type):
                    prop["bsonType"] = bson_type
                    break
            else:
                prop["bsonType"] = "string"

        # Help text
        if field.help_text:
            prop["description"] = field.help_text

        # Choices → enum
        if field.choices:
            prop["enum"] = [choice[0] for choice in field.choices]
            prop["description"] += f" Choices: {', '.join(f'{repr(v)} = {l}' for v, l in field.choices)}"

        schema["$jsonSchema"]["properties"][field.name] = prop

        # Required: not null AND not blank
        if not getattr(field, "null", True) and not getattr(field, "blank", True):
            schema["$jsonSchema"]["required"].append(field.name)
```

**Assessment:** Nautobot's models are rich with `help_text` and `choices`. A similar `generate_input_schema()` could auto-build `input_schema` dicts from function type hints using `inspect.signature`. This is P2 — reduces boilerplate for new tools but not blocking.

---

### 5. Request Lifecycle — Full Flow

**File:** `mcp_server/views.py`, `mcp_server/djangomcp.py`

```
Django WSGI Request (Mcp-Session-Id header)
    │
    ▼
MCPServerStreamableHttpView.get() / .post()  [DRF APIView]
    │
    ▼
DjangoMCP.handle_django_request(request)  [synchronized entry point]
    │
    ├── [non-stateless] Read "Mcp-Session-Id" → load Django SessionStore
    ├── [non-stateless] Attach session to request.session
    │
    ▼
async_to_sync(_call_starlette_handler(request, session_manager))
    │
    ├── Serialize Django request.body to bytes
    ├── Build ASGI Scope dict:
    │   {
    │     "type": "http",
    │     "scheme": "https" if request.is_secure() else "http",
    │     "method": request.method,
    │     "path": request.path,
    │     "query_string": request.META["QUERY_STRING"].encode(),
    │     "headers": [(k.lower(), v) for k,v in request.headers],
    │     "server": (request.get_host(), request.get_port()),
    │     "client": (request.META["REMOTE_ADDR"], 0),
    │   }
    ├── Build Starlette receive() / send() async functions
    │
    ▼
async with session_manager.run():  [StreamableHTTPSessionManager]
    │
    ▼
await session_manager.handle_request(scope, receive, send)
    │
    ▼
FastMCP MCP protocol handlers (list_tools, call_tool, etc.)
    │
    └── MCP tool execution
         │
         ▼
Django HttpResponse (Mcp-Session-Id in headers)
```

**Nautobot's current broken flow:**

```
Django request
    → mcp_view()
    → get_mcp_app()
    → FastMCP.http_app()(scope, receive, send)
    → asyncio.run(mcp_app(scope, receive, send))  ← BROKEN: loop destroyed after each request
         └── StreamableHTTPSessionManager.run() never entered as a running context
```

**The exact fix pattern:**

```python
# In view.py — replace asyncio.run() with async_to_sync + run():
from asgiref.sync import async_to_sync

async def _call_mcp(scope, receive, send, session_manager):
    async with session_manager.run():
        await session_manager.handle_request(scope, receive, send)

result = async_to_sync(_call_mcp)(scope, receive, send, session_manager)
```

Or more directly (pattern from django-mcp-server):

```python
from asgiref.sync import async_to_sync
result = async_to_sync(_call_starlette_handler)(request, self.session_manager)
```

---

### 6. Auth Integration — DRF View vs Nautobot Token Auth

**django-mcp-server DRF approach:**

```python
# urls.py — DRF authentication classes wired at URL routing level
path("mcp", MCPServerStreamableHttpView.as_view(
    authentication_classes=[
        import_string(cls) for cls in getattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES", [])
    ],
    permission_classes=[
        IsAuthenticated if getattr(settings, "DJANGO_MCP_AUTHENTICATION_CLASSES", None) else [],
    ],
), name="mcp_server_endpoint")

# MCPServerStreamableHttpView.get/post() just delegate to handle_django_request()
# DRF runs authentication BEFORE the view method is called:
#   1. Runs authentication classes → sets request.user
#   2. Runs permission classes → raises 403 if denied
#   3. handle_django_request() receives request with request.user already set
```

**django_request_ctx context variable pattern (for tool access):**

```python
django_request_ctx = contextvars.ContextVar("django_request")

async def _call_starlette_handler(django_request, session_manager):
    django_request_ctx.set(django_request)  # ← store at entry point
    ...

class _ToolsetMethodCaller:
    def __call__(self, *args, **kwargs):
        instance = self.class_(context=kwargs[self.context_kwarg],
                               request=django_request_ctx.get(SimpleNamespace()))
        # request.user is available in any tool without passing it explicitly
```

**Nautobot's current per-tool approach (from `auth.py`):**

```python
def get_user_from_request(request) -> User | AnonymousUser:
    auth_header = request.META.get("HTTP_AUTHORIZATION", "")
    if not auth_header.startswith("Token "):
        return AnonymousUser()
    token_key = auth_header[6:]
    token = Token.objects.select_related("user").get(key=token_key)
    return token.user
```

**Adaptation for Nautobot:** Replace DRF's pre-call authentication with manual token extraction at the start of `mcp_view()`. Store the user on the Django request object so all tools can access it without repeated DB lookups:

```python
# In mcp_view() — extract and cache user once at request entry:
user = get_user_from_request(django_request)
django_request._cached_mcp_user = user  # attach to request

# In tools:
user = tool_ctx.request._cached_mcp_user  # no additional DB query
```

**Request-level user caching pattern** (borrow from `_ToolsetMethodCaller`): Use a module-level `contextvars.ContextVar` to store the Django request so tools can access it without explicit passing:

```python
from contextvars import ContextVar
_nautobot_request_ctx: ContextVar[HttpRequest] = ContextVar("nautobot_request")

# In mcp_view():
_nautobot_request_ctx.set(request)

# In tools:
request = _nautobot_request_ctx.get()
user = getattr(request, "_cached_mcp_user", None) or get_user_from_request(request)
```

---

## Feature Dependencies

```
DjangoMCP.handle_django_request()
    ├──requires──> async_to_sync (WSGI→ASGI bridge)
    │                   └──requires──> _call_starlette_handler()
    │                                   └──requires──> StreamableHTTPSessionManager.run()
    │
    ├──requires──> Mcp-Session-Id header reading
    │                   └──optional──> Django SessionStore (for persistence — not needed for Nautobot)
    │
    └──enhances──> MCPToolset metaclass registry
                        └──requires──> global_mcp_server (module-level singleton)

async_to_sync (instead of asyncio.run())
    └──enables──> StreamableHTTPSessionManager.run() context
                      └──enables──> FastMCP session dict persistence across requests
                              └──enables──> MCPSessionState progressive disclosure (currently broken)

MCPToolRegistry singleton (nautobot)
    └──conflicts──> ToolsetMeta metaclass registry (django-mcp-server)
                        (mutually exclusive approaches; keep Nautobot's manual API)

django_request_ctx context var (django-mcp-server)
    └──enables──> Tools access Django request without explicit passing
                      └──optional──> Nautobot: use for user caching (P1)
```

---

## MVP Definition

### Launch With (v1.1 — current refactor)

- [ ] **Fix `asyncio.run()` → `async_to_sync` + `session_manager.run()`** — restores session state; the single most critical fix
- [ ] **Fix `Server.request_context.get()` LookupError** — restores progressive disclosure (depends on P0 fix)
- [ ] **Thread-safe locking for `get_mcp_app()` singleton** — double-checked locking with `threading.Lock()`
- [ ] **Derive server address from `request.get_host()`** in ASGI scope — replace hardcoded `127.0.0.1:8080`
- [ ] **Request-level user caching in auth layer** — `@lru_cache` on token key or `contextvars.ContextVar`
- [ ] All existing unit tests pass with session state working end-to-end

### Add After Validation (v1.x)

- [ ] **`generate_input_schema()` helper** — auto-build JSON Schema from function type hints using `inspect.signature`
- [ ] **`_nautobot_request_ctx` context variable** — store Django request at entry point, access from tools without passing
- [ ] DRY session access: user cached on request, accessed via context var from all tools

### Future Consideration (v2+)

- [ ] Metaclass-based tool registry for ergonomic auto-discovery (if tools grow to 50+)
- [ ] Django session backend delegation for persistent scoping (if multi-worker deployment needed)
- [ ] DRF integration for apps that have existing DRF views

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Fix `asyncio.run()` → `async_to_sync` + `session_manager.run()` | HIGH — session state is fundamentally broken | LOW (~10 lines) | **P0** |
| Fix `Server.request_context.get()` LookupError in progressive disclosure | HIGH — progressive disclosure is fundamentally broken | MEDIUM (depends on P0) | **P0** |
| Thread-safe `get_mcp_app()` singleton (double-checked locking) | MEDIUM — race condition under concurrent load | LOW (~5 lines) | **P1** |
| Request-level user caching (`contextvars` or `@lru_cache`) | MEDIUM — eliminates redundant DB queries per tool call | LOW (~3 lines) | **P1** |
| Derive server address from `request.get_host()` in ASGI scope | LOW — affects logging/debugging only | LOW (~2 lines) | **P1** |
| `generate_input_schema()` from type hints | MEDIUM — reduces boilerplate for new tools | MEDIUM | **P2** |
| `django_request_ctx` context var pattern | MEDIUM — DRY user access from tools | LOW | **P2** |
| Metaclass-based tool registry | MEDIUM — ergonomic for large tool sets | HIGH | **P2** |
| Django session backend delegation | MEDIUM — session survives restarts | MEDIUM | **P2** |

**Priority key:**
- **P0:** Must fix — session state and progressive disclosure are completely broken
- **P1:** Should fix — correctness/performance issues identified in analysis
- **P2:** Nice to have — design improvements, not correctness issues

---

## Competitor Feature Analysis

| Feature | django-mcp-server | nautobot-app-mcp-server | Our Approach |
|---------|-------------------|-------------------------|--------------|
| Session management | Django `SessionStore` via `Mcp-Session-Id` | FastMCP in-memory (broken) | Fix `async_to_sync` — in-memory is fine for Docker single-process |
| Tool registration | Metaclass auto-discovery | Manual `register_mcp_tool()` | Keep manual — explicit, sufficient for ~10 tools |
| JSON Schema generation | Auto from model fields | Hand-written dicts | P2: type-hint based helper |
| DRF → MCP decorator | Full CRUD via `@drf_publish_*_mcp_tool` | None (Nautobot has no DRF) | N/A |
| Progressive disclosure | Not implemented | `mcp_enable_tools`/`disable_tools`/`list_tools` | Keep — Nautobot-specific differentiator |
| Tool scope hierarchy | Not implemented | `get_by_scope()` with startswith | Keep — Nautobot-specific differentiator |
| Auth placement | DRF APIView level (runs before view) | Per-tool `get_user_from_request()` | Add request-level user caching |
| Auth user access in tools | `django_request_ctx` context var | Explicit passing per tool | P2: borrow context var pattern |
| MongoDB query DSL | Full `$match`/`$lookup`/`$group` pipeline | Not needed (Nautobot ORM) | N/A |
| ASGI scope construction | Full (scheme, host, port, headers) | Partial (hardcoded `127.0.0.1:8080`) | P1: derive from request |
| MCP initialization handshake | `request.data.get("method") == "initialize"` check | Not explicitly handled | Not needed — FastMCP handles this |
| Global MCP server | Module-level `global_mcp_server = DjangoMCP(...)` | Lazy `get_mcp_app()` | Keep lazy (avoids Django ORM race at import) |

---

## Sources

- https://github.com/gts360/django-mcp-server (Apache-2.0)
- `mcp_server/djangomcp.py` — `DjangoMCP`, `MCPToolset`, `ToolsetMeta`, `global_mcp_server`, `_ToolsetMethodCaller`, `django_request_ctx`, `_call_starlette_handler`
- `mcp_server/views.py` — `MCPServerStreamableHttpView`, URL routing with DRF auth config
- `mcp_server/query_tool.py` — `generate_json_schema()`, `ModelQueryToolset`, `ModelQueryToolsetMeta`, `_QueryExecutor`
- `docs/dev/mcp-implementation-analysis.md` — existing correctness analysis of nautobot-app-mcp-server
- `nautobot_app_mcp_server/mcp/server.py` — current broken `_list_tools_mcp` override
- `nautobot_app_mcp_server/mcp/session_tools.py` — current `MCPSessionState` + session tools

---
*Feature research for: MCP Server django-mcp-server patterns for nautobot-app-mcp-server refactor*
*Researched: 2026-04-03*
*Confidence: HIGH — all code patterns extracted directly from source; conclusions validated against implementation analysis*
