# My MCP Server

Learn how AI agents use MCP. This project has an **MCP server** that wraps three free public APIs, and **agent clients** that connect to it over **Streamable HTTP**. The server is protected with an API key.

```
my_mcp_server/
├── mcp_server/          the MCP server          (uv project)
│   └── Dockerfile       the server as a container image, for AWS
├── langchain_client/    a LangChain agent       (uv project)
├── langgraph_client/    a LangGraph agent       (uv project)
└── guides/              read these in order, after this README
    ├── 01_AUTH_NOTES.md               how auth works: protecting the server, and tools calling protected APIs
    ├── 02_MCP_AUTH_IMPLEMENTATION.md  step by step: how the server's auth was built
    ├── 03_OAUTH_GUIDE.md              users sign in at a chat frontend: OAuth from the browser to your REST API
    └── 04_DEPLOYMENT_GUIDE.md         deploy the server to AWS: ECR + ECS Fargate
```

Each code folder is its own uv project with its own dependencies. The clients never import the server's code. They only talk to it over HTTP, the same way any MCP client would.

You need [uv](https://docs.astral.sh/uv/).

## 1. The MCP server

| Kind     | Name                            | What it does                                                                                                   | API                                                     |
| -------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Tool     | `get_weather(city)`             | Current temperature, humidity and wind for a city                                                              | [Open-Meteo](https://open-meteo.com)                    |
| Tool     | `get_products(category, limit)` | Products from an online store, optionally by category                                                          | [Fake Store API](https://fakestoreapi.com)              |
| Tool     | `get_users()`                   | 10 sample users with email, city and company. Plays a **protected** API: the tool sends the server's own token | [JSONPlaceholder](https://jsonplaceholder.typicode.com) |
| Resource | `info://about`                  | A short description of this server                                                                             | —                                                       |
| Prompt   | `weather_report(city)`          | Asks for a friendly weather report and what to wear                                                            | —                                                       |

**Who uses what?**

- **Tools**: the AI model decides when to call them.
- **Resources**: the app reads them. They are read-only data with an address (a URI).
- **Prompts**: the user picks them. They are reusable instruction templates.

### Run it

```bash
cd mcp_server
cp .env.example .env      # MCP_API_KEY and USERS_API_TOKEN; the demo values work as they are
uv run server.py
```

The server listens at **http://127.0.0.1:9001/mcp**. Leave it running in its own terminal. Each tool call prints a `[tool] ...` line there.

To run it in AWS instead, follow [guides/04_DEPLOYMENT_GUIDE.md](guides/04_DEPLOYMENT_GUIDE.md): it builds a Docker image, pushes it to ECR, and runs it on ECS Fargate behind a load balancer.

### Auth in one minute

There are two layers, each with its own key in `mcp_server/.env`:

1. **`MCP_API_KEY`** protects the server. Every request from Agent must send `Authorization: Bearer <MCP_API_KEY>`, or the server answers `401 Unauthorized`.
2. **`USERS_API_TOKEN`** is the server's own credential for the Users API. `get_users` tool from of mcp server sends it. The server never forwards the client's key to the API.

[guides/01_AUTH_NOTES.md](guides/01_AUTH_NOTES.md) explains why the layers are separate, what changes for production (OAuth tokens from an identity provider), and how LangChain and LangGraph connect to a protected server. [guides/02_MCP_AUTH_IMPLEMENTATION.md](guides/02_MCP_AUTH_IMPLEMENTATION.md) walks through building it step by step, with test commands and troubleshooting. [guides/03_OAUTH_GUIDE.md](guides/03_OAUTH_GUIDE.md) shows what changes when users sign in at a web chat frontend, and tools act as that user all the way to your REST API.

### Try it with MCP Inspector

MCP Inspector is a browser UI that acts as an MCP client. It needs Node.js.

```bash
npx @modelcontextprotocol/inspector
```

Set **Transport Type** to `Streamable HTTP` and **URL** to `http://127.0.0.1:9001/mcp`. In the authentication or headers section, add the header `Authorization` with the value `Bearer 12345ABCDE` (your `MCP_API_KEY`). Then click **Connect** and open the Tools, Resources and Prompts tabs.

Things to try:

- Connect **without** the header first and see the `401`.
- `get_weather` with `Pune`, then with a made-up city to see the error the model would get.
- `get_products` with no arguments, then with category `electronics`.
- `get_users`, and watch the server terminal print who called it.
- Look at each tool's input schema. The type hints in `server.py` became the JSON schema.

### Try it with Claude Code

`.mcp.json` registers this server with Claude Code and sends `Authorization: Bearer ${MCP_API_KEY}` from your shell. Start the server, then start Claude Code in this folder with the key set:

```bash
MCP_API_KEY=12345ABCDE claude
```

Approve `my-mcp-server` when it asks. Then ask _"What's the weather in Mumbai?"_, or run `/mcp` to see the server's tools.

## 2. The LangChain agent

`langchain_client/agent.py` connects to the server and walks through five steps:

1. Connect to the MCP server over Streamable HTTP, **sending the API key in a header**
2. Read the `info://about` **resource**
3. Load the **tools** and give them to an OpenAI-powered agent
4. Use the `weather_report` **prompt**
5. Chat with the agent. It prints each tool it calls, like `🔧 get_weather({'city': 'Pune'})`

### Run it

With the server running, open a second terminal:

```bash
cd langchain_client
cp .env.example .env      # add your OPENAI_API_KEY; MCP_API_KEY must match mcp_server/.env
uv run agent.py
```

Questions to try:

- _What's the weather in London?_
- _Show me 3 electronics products under $100._
- _Which users work at a company with "Group" in its name?_
- _Is it warmer in Delhi or Chennai right now?_ (two tool calls)

To use a different OpenAI model, change `MODEL` at the top of `agent.py`.

## 3. The LangGraph agent

`langgraph_client/agent.py` does the same five steps as the LangChain agent. The difference is step 3: instead of `create_agent()`, which hides the agent loop, it **builds the loop as a graph** you can read:

```
             ┌─────────┐  tool calls?  ┌─────────┐
   START ──▶ │  agent  │ ───── yes ──▶ │  tools  │ ── calls the MCP server over HTTP
             │ (model) │ ◀──────────── │  (MCP)  │
             └─────────┘               └─────────┘
                  │ no: the answer is ready
                  ▼
                 END
```

New ideas compared with the LangChain agent:

| Idea | In the code | Why it matters |
|---|---|---|
| **Nodes and edges** | `StateGraph(MessagesState)`, `add_node`, `add_edge` | You see and control every step of the loop |
| **Conditional edge** | `add_conditional_edges("agent", tools_condition)` | The model's reply decides where to go next: to the tools, or to the end |
| **Checkpointer memory** | `compile(checkpointer=InMemorySaver())` and `thread_id` | The graph remembers the conversation, so each turn sends only the new message |
| **Streaming steps** | `astream(..., stream_mode="updates")` | Prints each node as it runs: `[agent] → get_weather(...)`, then `[tools] ← get_weather: ...` |
| **Step limit** | `"recursion_limit": 10` | Stops a looping agent. LangGraph's default is over 10,000 steps, so always set your own |

The MCP part (connecting with the API key, the resource, the tools, the prompt) is the same code as in the LangChain agent. **LangGraph doesn't change how you talk to MCP.**

### Run it

With the server running, open a second terminal:

```bash
cd langgraph_client
cp .env.example .env      # add your OPENAI_API_KEY; MCP_API_KEY must match mcp_server/.env
uv run agent.py
```

Questions to try:

- _Is it warmer in Pune than there right now?_ ("there" means Mumbai, from the prompt's report: that's the checkpointer's memory at work)
- _Which users live in Gwenborough?_ (the protected `get_users` tool)
- _What's the weather in Xyzzyville?_ (watch the tool error come back, marked `(error)`)
- _Show me 3 electronics products under $100._

## 4. Guides

Once the server and both agents run, read the guides in `guides/`, in this order. Each one builds on the ones before it.

| # | Guide | What you'll learn |
|---|---|---|
| 1 | [Auth notes](guides/01_AUTH_NOTES.md) | *Why*: the two auth layers, why the server never forwards a client's token, and how agents connect to a protected server |
| 2 | [MCP auth implementation](guides/02_MCP_AUTH_IMPLEMENTATION.md) | *How*: protecting `server.py` step by step, with test commands and troubleshooting |
| 3 | [OAuth guide](guides/03_OAUTH_GUIDE.md) | Users sign in at a web chat frontend, and tools act as that user all the way to your REST API |
| 4 | [Deployment guide](guides/04_DEPLOYMENT_GUIDE.md) | Run the server in AWS: Docker, ECR and ECS Fargate behind a load balancer |
