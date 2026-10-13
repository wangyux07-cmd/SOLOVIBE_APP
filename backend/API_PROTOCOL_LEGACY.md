# SoloVibe AI Agent API Protocol Specification

> Historical prototype specification. The running Stage 3 API contract is implemented in
> [`main.py`](main.py), with LangGraph in [`agent_graph.py`](agent_graph.py).
> `POST /api/chat` requires `thread_id`, `request_id`, and `expected_revision`;
> `GET /api/conversations/{thread_id}/plans` reads the latest persisted plan set.
> The SSE endpoints described below are not active in the redesign.

**Version:** 2.0.0 (Industrial-Grade)
**Status:** Protocol Redesign - Event-Driven Architecture
**Last Updated:** 2026-06-06

---

## 1. Overview

This document defines a production-grade API protocol for a stateful AI Agent conversation system. The protocol enforces clear separation of concerns between conversation lifecycle management, agent reasoning, and client interaction.

### 🎯 Design Philosophy

- **State-driven, not message-driven**: All AI reasoning must use structured state
- **Event-based, not tag-based**: All streaming responses use structured events
- **Thread-aware**: Every request maintains conversation continuity
- **Tool-safe**: Clear boundaries for external tool execution

### 🔑 Core Concepts

| Concept | Definition | Responsibility |
|---------|------------|----------------|
| `thread` | Persistent conversation container | Lifecycle management |
| `state` | Structured memory (JSON) | Decision making |
| `message` | Raw conversation logs | History only |
| `checkpoint` | Agent execution snapshot | Recovery/resume |

---

## 2. Core Architecture

### 2.1 System Layers

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   API Layer     │────>│   Conversation  │────>│   Agent Layer   │
│ (HTTP/SSE)      │     │    Service      │ (reasoning)     │ (tools)
└─────────────────┘     └─────────────────┘     └─────────────────┘
       │                          │                         │
       │                          V                         V
       │                   ┌─────────────────┐     ┌─────────────────┐
       │                   │   Data Layer    │────>│  Security Layer │
       │                   │ (PostgreSQL)    │     │ (auth/risk)     │
       V                   └─────────────────┘     └─────────────────┘
┌─────────────────┐
│    Client       │
│ (Web/Mobile)    │
└─────────────────┘
```

### 2.2 Data Flow

```
Client Request
    │
    ├─→ Thread Resolution
    │     └─→ get_or_create_thread()
    │
    ├─→ State Loading
    │     └─→ load_thread_state()
    │
    ├─→ Agent Reasoning
    │     └─→ process_message(state)
    │
    ├─→ State Update
    │     └─→ save_thread_state()
    │
    └─→ Response Streaming
          └─→ event-based SSE
```

---

## 3. API Specification

### 3.1 HTTP Endpoints

#### POST /api/chat
**Purpose:** Main conversation endpoint with state management

**Request Schema:**
```json
{
  "type": "object",
  "properties": {
    "message": {
      "type": "string",
      "description": "User input message",
      "minLength": 1
    },
    "thread_id": {
      "type": "string",
      "description": "Optional: Conversation thread ID for continuity",
      "pattern": "^(thread_[a-f0-9]{16}|[a-f0-9-]{36})$"
    },
    "stream": {
      "type": "boolean",
      "description": "Whether to use streaming response",
      "default": true
    }
  },
  "required": ["message"]
}
```

**Response Schema (Non-Streaming):**
```json
{
  "type": "object",
  "properties": {
    "response": {
      "type": "string",
      "description": "AI generated response text"
    },
    "thread_id": {
      "type": "string",
      "description": "Thread ID for next request",
      "required": true
    },
    "state_info": {
      "type": "object",
      "description": "Debug info about current state",
      "properties": {
        "has_location": {"type": "boolean"},
        "location_resolved": {"type": "boolean"},
        "needs_user_input": {"type": "boolean"}
      }
    }
  },
  "required": ["response", "thread_id"]
}
```

**Headers:**
- `Content-Type: application/json`
- `X-Thread-ID: {thread_id}`

#### GET /api/health
**Purpose:** Service health check

**Response:**
```json
{
  "status": "healthy",
  "version": "2.0.0",
  "timestamp": "2026-06-06T...".
  "features": {
    "stateful_conversations": true,
    "real_time_tools": true,
    "streaming_responses": true
  }
}
```

---

## 4. Thread Lifecycle Rules (VERY IMPORTANT)

### 4.1 Thread Creation Logic

**NEW THREAD conditions:**
1. ❌ No `thread_id` parameter provided
2. ❌ User explicitly requests new topic
3. ❌ System detects completely different intent
4. ❌ Session timeout (>24h inactivity)

**REUSE THREAD conditions:**
1. ✅ Valid `thread_id` provided
2. ✅ Last activity < 24 hours
3. ✅ Thread state exists
4. ✅ Same user/session context

### 4.2 Intent-Based Rules

**New Topic Keywords:**
```
"重新开始", "换个话题", "别说这个了", "我们聊点别的",
"new topic", "different question", "let's change subject"
```

**New Thread Detection:**
1. Lexical analysis for keywords
2. Embedding similarity < threshold
3. User explicitly states "new conversation"

### 4.3 Thread IDs Format

**Stable Threads:**
- `thread_{md5(user_token)[:16]}` - For authenticated users
- `thread_{md5(session_token)[:16]}` - For session-based users

**Ephemeral Threads:**
- `{uuid4()}` - Temporary anonymous sessions

---

## 5. State Management Design (CORE SECTION)

### 5.1 State Structure

```typescript
interface ThreadState {
  // Core metadata
  thread_id: string;
  status: "active" | "waiting_confirmation" | "completed";
  updated_at: string;

  // Memory slots
  address_slot?: {
    location: string;
    lat: number;
    lng: number;
    source: "user_provided" | "inferred" | "last_known";
    confidence: number; // 0-1
    updated_at: string;
  };

  user_preferences?: {
    business_style: "quiet_study" | "social" | "cozy_rest";
    budget_range: [number, number];
    accessibility_needs: string[];
    preferred_categories: string[];
  };

  conversation_context?: {
    current_task: "location_query" | "business_search" | "booking_flow";
    pending_action?: {
      tool_name: string;
      params: any;
      require_confirmation: boolean;
    };

    // Emotional context
    user_mood: "stressed" | "curious" | "lonely" | "adventurous";
    timestamp: string;
  };

  // Raw dialog history (for reference only, not reasoning)
  messages: Array<{
    role: "user" | "assistant";
    content: string;
    timestamp: string;
  }>;
}
```

### 5.2 State Persistence Rules

**Persistence Frequency:**
- After EVERY successful agent turn
- Before tool execution
- After confirmation received

**State Loading Priority:**
```
Supabase (persistent) → Redis (cache) → Memory → New session
```

### 5.3 State Lifecycle

```
New Session
    ↓
[Address Unresolved]
    ↓
User Provides Location → [Address Resolved]
    ↓
[Business Search Active]
    ↓
[Booking Flow Started] → [Confirmation Pending] → [Complete]
```

---

## 6. SSE Streaming Protocol (event-based)

### 6.1 Event Types

**Response Events:**
```
event: empathy
data: { "text": "我理解你的心情" }
```

```
event: plan
data: { "id": "plan-001", "steps": ["定位", "搜索", "推荐"] }
```

```
event: location_request
data: { "prompt": "你在哪个地铁站附近？" }
```

```
event: business_recommendation
data: { "name": "星巴克", "distance": "300m", "highlights": ["安静", "WiFi"] }
```

**Control Events:**
```
event: require_confirmation
data: { "action": "booking", "confirm_text": "确认预订咖啡馆吗？" }
```

```
event: complete
data: { "summary": "对话完成" }
```

### 6.2 Event Schema Standards

```typescript
// ALL events must follow this base schema
interface StreamEvent {
  id?: string;        // Optional event ID
  type: string;       // Event type
  timestamp: string;  // ISO8601
  data: any;          // Event payload
}
```

### 6.3 Streaming Flow Examples

**Location Query Flow:**
```
event: empathy
data: { "text": "听起来你今天需要一些安静时光" }

event: location_request
data: { "prompt": "你在哪个地铁站附近？" }
event: complete
data: {}
```

**Business Recommendation Flow:**
```
event: empathy
data: { "text": "找到了几个适合你的好地方" }

event: business_recommendation
data: { "name": "图书馆咖啡区", "description": "安静、WiFi", "distance": "200m" }

event: plan
data: { "id": "route-001", "steps": ["步行3分钟", "到达目的地"] }

event: complete
data: { "summary": "已为你规划好路线" }
```

**Booking Confirmation Flow:**
```
event: empathy
ndata: { "text": "我找到了一个很棒的地方" }

event: require_confirmation
data: { "action": "create_booking", "details": { "place": "安静咖啡", "time": "14:00" } }

event: complete
data: { "status": "waiting_user_confirmation" }
```

---

## 7. Agent Behavior Rules

### 7.1 Decision Making Protocol

**DO (Priority Decision Sources):**
1. ✅ `state.address_slot.location` exists → DO NOT ask for location
2. ✅ `state.user_preferences` exists → Use preferences in search
3. ✅ `state.conversation_context.current_task` → Follow task flow
4. ✅ `state.conversation_context.user_mood` → Adapt empathy level

**DON'T (Anti-Patterns):**
1. ❌ Raw message analysis for location detection
2. ❌ Repeat the same question in the same thread
3. ❌ Create new sub-task without task completion
4. ❌ Make assumptions without user confirmation

### 7.2 Notallowed Message Triggers

**NEVER Extract Location From:**
- Emotional statements without explicit location
  - "心情不好" → ❌ Not a location
  - "被上司骂了" → ❌ Not a location
  - "工作压力大" → ❌ Not a location

**NOT Considered Reliable Location Sources:**
- Metaphorical references
  - "我在城市中央" → ❌ Too vague
  - "我在世界尽头" → ❌ Not literal
- Temporary emotional states
  - "我在抑郁症中" → ❌ Not physical location

### 7.3 Location Resolution Strategy

**Tier 1 - Direct Provision:**
1. ✅ "我在徐家汇" → Direct accept
2. ✅ "上海大学站" → Direct accept
3. ✅ "静安区地铁站" → Direct accept

**Tier 2 - City + Area:**
1. ⚠️ "我在上海" → Ask for suburb/district
2. ⚠️ "我在北京" → Ask for area/metro line

**Tier 3 - Actions/Behaviors:**
1. ❌ "想去咖啡馆" → DON'T infer any location
2. ❌ "心情不好需要安慰" → MUST ask for location

---

## 8. Tool Calling Protocol

### 8.1 Tool Execution Schema

```typescript
interface ToolCall {
  id: string;
  tool: "search_business" | "get_location" | "create_booking";
  params: Record<string, any>;
  confidence: number; // 0-1
  require_confirmation: boolean;
}
```

### 8.2 Confirmation-Required Tools

- `create_booking`: Always require confirmation
- `spend_money`: Always require confirmation
- `share_personal_data`: Always require confirmation
- `make_reservation`: Always require confirmation

### 8.3 Auto-Execute Tools

- `search_business`: Auto-execute (read-only)
- `get_location`: Auto-execute (read-only)
- `get_weather_info`: Auto-execute (read-only)

---

## 9. Error Handling

### 9.1 Error Categories

**Category A - Thread Issues:**
- `THREAD_NOT_FOUND`: Request `thread_id` doesn't exist
- `THREAD_EXPIRED`: Thread older than 24h
- `THREAD_CORRUPTED`: State structure invalid

**Category B - State Issues:**
- `STATE_PERSISTENCE_FAILED`: Cannot save/load state
- `STATE_SCHEMA_MISMATCH`: Version incompatibility
- `INVALID_STATE_TRANSITION`: Illegal state change

**Category C - Agent Issues:**
- `AGENT_PROCESSING_TIMEOUT`: Reasoning took too long
- `TOOL_EXECUTION_FAILED`: External tool failure
- `LLM_RESPONSE_UNRELIABLE`: Nonsense output

### 9.2 Recovery Strategies

**Mild Errors (Soft Recovery):**
- Cache temporary failure → Warn + retry
- State save failure → Continue in memory
- Tool timeout → Provide fallback info

**Severe Errors (Hard Recovery):**
- Corrupted thread → Create new thread + log old thread_id
- All persistent storage failed → Graceful degradation to memory-only
- LLM completely broken → Return apology + disable features

### 9.3 Error Response Schema

```json
{
  "error": {
    "code": "THREAD_NOT_FOUND",
    "message": "Provided thread_id does not exist",
    "thread_id": "original-or-new-thread-id",
    "suggestion": "Start new conversation or provide valid thread_id"
  },
  "response": "抱歉，找不到这个对话，让我们重新开始吧。你在哪里？",
  "thread_id": "new-thread-id-if-created"
}
```

---

## 10. Data Model

### 10.1 Supabase Tables

**threads table:**
```sql
thread_id VARCHAR(36) PRIMARY KEY,
status VARCHAR(20) NOT NULL CHECK (status IN ('active', 'waiting_confirmation', 'completed')),
user_token VARCHAR(64), -- For authenticated users
session_token VARCHAR(64), -- For session-based users
created_at TIMESTAMPTZ DEFAULT NOW(),
updated_at TIMESTAMPTZ DEFAULT NOW(),
last_activity_at TIMESTAMPTZ DEFAULT NOW()
```

**thread_states table:**
```sql
state_id SERIAL PRIMARY KEY,
thread_id VARCHAR(36) REFERENCES threads(thread_id),
state_version INTEGER NOT NULL,
state_json JSONB NOT NULL, -- Full state structure
created_at TIMESTAMPTZ DEFAULT NOW().
is_current BOOLEAN DEFAULT TRUE
```

**thread_messages table:**
```sql
message_id SERIAL PRIMARY KEY,
thread_id VARCHAR(36) REFERENCES threads(thread_id),
role VARCHAR(10) NOT NULL CHECK (role IN ('user', 'assistant')),
content TEXT NOT NULL,
timestamp TIMESTAMPTZ DEFAULT NOW(),
metadata JSONB -- Optional message metadata
```

**tool_executions table:**
```sql
execution_id SERIAL PRIMARY KEY,
thread_id VARCHAR(36) REFERENCES threads(thread_id),
tool_name VARCHAR(50) NOT NULL,
params JSONB NOT NULL,
result JSONB,
status VARCHAR(20) NOT NULL,
executed_at TIMESTAMPTZ DEFAULT NOW(),
confirmed_by_user BOOLEAN DEFAULT FALSE
```

### 10.2 Indexes

```sql
-- For performance
CREATE INDEX idx_threads_user ON threads(user_token);
CREATE INDEX idx_threads_session ON threads(session_token);
CREATE INDEX idx_threads_activity ON threads(last_activity_at DESC);
CREATE INDEX idx_states_current ON thread_states(thread_id, is_current);
CREATE INDEX idx_messages_thread ON thread_messages(thread_id, timestamp DESC);
```

---

## 11. Security & Risk Control

### 11.1 Input Validation

**Required Fields:**
- All user inputs → Sanitize + validate length
- Thread ID → Validate format + existence
- Tool parameters → Schema validation

**Rate Limiting:**
- Per user/session: 30 req/min
- Per tool: 10 calls/min per thread
- Sensitive actions: 5/hr per user

### 11.2 Privacy Protection

**Never Store:**
- Raw authentication tokens
- Personal identifiable information without encryption
- Sensitive location history older than 30 days

**User Data Rights:**
- Session deletion on request
- State clearing on command
- Conversation export capability

### 11.3 Action Verification

**High-Risk Actions (+2FA):**
- Financial transactions
- Personal data sharing
- Booking confirmations
- Phone number reveals

---

## 12. Example Flows

### 12.1 Location Update Flow

```javascript
// Client sends message with location
{
  "message": "我昨天搬到了宝山区",
  "thread_id": "thread_abc123"
}

// Backend processes:
// Step 1: Loads current state
// Step 2: Updates address_slot
// Step 3: Saves new state
// Step 4: Responds with confirmation

// Response:
{
  "response": "好的，现在我知道你在宝山区了！你们区域有很多好地方哦～",
  "thread_id": "thread_abc123",
  "state_info": {
    "has_location": true,
    "location_resolved": true,
    "needs_user_input": false
  }
}
```

### 12.2 Context Preservation Flow

```javascript
// User: "心情不好"
// System: "你在哪里？"  [thread_123, needs location]
// User: "静安区"

// Response preserves the emotional context
{
  "response": "在静安区一定有很多让你放松的地方。告诉我你需要什么样的环境？安静学习还是温暖陪伴？",
  "thread_id": "thread_123",
  "state_info": {
    "has_location": true,
    "location_resolved": true,
    "needs_user_input": false
  }
}
```

### 12.3 Thread Migration Flow

```javascript
// Stale thread (25h old)
{
  "message": "心情还是不好",
  "thread_id": "stale-thread-id"
}

// Backend detects expiration, creates new thread,
// carries forward ONLY the location state

{
  "response": "很高兴再次见到你！虽然是很久前的对话，但我记得你在静安区。今天需要什么呢？",
  "thread_id": "new-thread-id",
  "state_info": {
    "has_location": true,
    "location_resolved": false,
    "needs_user_input": false
  }
}
```

---

## 13. Implementation Checklist

### 🔄 Protocol Compliance (MUST CHECK)

- [ ] **Thread rules clearly defined** ✓
- [ ] **State is primary memory source** ✓
- [ ] **SSE is event-based (not tag-based)** ✓
- [ ] **Agent rules separated from API layer** ✓
- [ ] **Tool calls are structured** ✓
- [ ] **Lifecycle rules are unambiguous** ✓
- [ ] **No reliance on raw message for decisions** ✓

### 🛠 Implementation Requirements

- [ ] Update all LangGraph agent output to use event structure
- [ ] Modify streaming middleware to emit events instead of tags
- [ ] Implement proper thread ID generation/reuse logic
- [ ] Build state persistence layer with versioning
- [ ] Create comprehensive error handling with recovery
- [ ] Add unit tests for thread lifecycle scenarios
- [ ] Update frontend to handle new SSE events

### 📋 Data Migration Plan

- [ ] Schema migration for new table structures
- [ ] Data transformation for existing threads
- [ ] Backfill tool execution records
- [ ] Test backup and recovery procedures

---

**END OF PROTOCOL SPECIFICATION**

> This protocol ensures deterministic, predictable AI behavior through state-driven reasoning rather than message analysis. Implement correctly for robust conversation continuity.
