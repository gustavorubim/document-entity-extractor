"""ReAct-style chat agent for natural language database queries."""

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from google import genai

from .config import GEMINI_MODEL, GOOGLE_API_KEY
from .database import execute_sql
from .schema_loader import get_active_schema

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 5


@dataclass
class AgentStep:
    """A single step in the agent's reasoning process."""

    thought: str
    action: str | None = None
    action_input: str | None = None
    observation: str | None = None


@dataclass
class ChatResponse:
    """Response from the chat agent."""

    answer: str
    steps: list[AgentStep] = field(default_factory=list)
    error: str | None = None


def get_client() -> genai.Client:
    """Get configured Gemini client."""
    return genai.Client(api_key=GOOGLE_API_KEY)


def build_schema_context() -> str:
    """Build a description of the database schema for the agent."""
    schema = get_active_schema()

    lines = ["## Database Schema\n"]

    # Documents table (always present)
    lines.append("### Table: documents")
    lines.append("- id: INTEGER PRIMARY KEY")
    lines.append("- filename: TEXT")
    lines.append("- file_type: TEXT")
    lines.append("- upload_date: TIMESTAMP")
    lines.append("- raw_text: TEXT")
    lines.append("- status: TEXT (pending, processing, completed, error)")
    lines.append("")

    # Root table from schema
    root = schema.get("root", {})
    root_table = root.get("table", "contracts")
    doc_fk = root.get("document_fk", {})

    lines.append(f"### Table: {root_table}")
    lines.append(f"- id: INTEGER PRIMARY KEY")
    lines.append(f"- {doc_fk.get('column', 'document_id')}: INTEGER (FK to documents)")

    # Add scalar fields to root table
    for fld in schema.get("fields", []):
        if fld.get("type") != "array":
            sql = fld.get("sql", {})
            if sql.get("table") == root_table:
                col = sql.get("column", fld["name"])
                col_type = sql.get("type", "TEXT")
                desc = fld.get("description", "")
                lines.append(f"- {col}: {col_type}" + (f" -- {desc}" if desc else ""))

    # Extra columns
    for extra in root.get("extra_columns", []):
        lines.append(f"- {extra['name']}: {extra.get('type', 'TEXT')}")

    lines.append("")

    # Child tables from array fields
    for fld in schema.get("fields", []):
        if fld.get("type") == "array":
            sql = fld.get("sql", {})
            table_name = sql.get("table", fld["name"])
            fk = sql.get("fk", {})

            lines.append(f"### Table: {table_name}")
            lines.append(f"- id: INTEGER PRIMARY KEY")
            lines.append(f"- {fk.get('column', 'parent_id')}: INTEGER (FK to {root_table})")

            for col in sql.get("columns", []):
                col_name = col.get("name", "value")
                col_type = col.get("type", "TEXT")
                lines.append(f"- {col_name}: {col_type}")

            lines.append("")

    return "\n".join(lines)


def build_system_prompt() -> str:
    """Build the system prompt for the ReAct agent."""
    schema_context = build_schema_context()

    return f"""You are a helpful database assistant that answers questions about document data stored in a SQLite database.

{schema_context}

## CRITICAL RULES
1. You have NO knowledge of the actual data in the database
2. You MUST use execute_sql to query the database before answering ANY question about data
3. NEVER guess, assume, or make up data - always query first
4. Base your answers ONLY on the actual query results

## Your Task
Answer user questions about the data in this database by querying it.

## Response Format
You MUST follow this exact format:

Thought: [what you need to find out]
Action: execute_sql
Action Input: [your SQL query]

After seeing the Observation (query results), you can either:
- Query again if you need more information
- Provide your final answer based on the results

When ready to answer:
Thought: [summary of what the data shows]
Final Answer: [your answer based on the query results]

## Example

User: How many documents are there?

Thought: I need to count the documents in the database. I'll query the documents table.
Action: execute_sql
Action Input: SELECT COUNT(*) as count FROM documents

Observation: | count |
| --- |
| 10 |

Total: 1 row(s)

Thought: The query shows there are 10 documents in the database.
Final Answer: There are 10 documents in the database.

## Important Notes
- Only use SELECT statements (the database is read-only)
- Use proper SQL syntax for SQLite
- Join tables as needed to answer complex questions
- ALWAYS query the database - never answer from memory or assumptions"""


def parse_agent_response(text: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse the agent's response to extract thought, action, action_input, and final_answer.

    Returns all components found. The caller decides priority based on state
    (e.g., prefer final_answer if we've already queried the database).
    """
    thought = None
    action = None
    action_input = None
    final_answer = None

    # Extract thought
    thought_match = re.search(r"Thought:\s*(.+?)(?=Action:|Final Answer:|$)", text, re.DOTALL)
    if thought_match:
        thought = thought_match.group(1).strip()

    # Extract Action if present
    action_match = re.search(r"Action:\s*(\w+)", text)
    if action_match:
        action = action_match.group(1).strip()

        # Extract action input - handle multi-line SQL
        # Stop at Observation (which would be hallucinated) or end of text
        input_match = re.search(r"Action Input:\s*(.+?)(?=Thought:|Action:|Final Answer:|Observation:|$)", text, re.DOTALL)
        if input_match:
            action_input = input_match.group(1).strip()
            # Clean up markdown code blocks if present
            if action_input.startswith("```"):
                action_input = re.sub(r"^```(?:sql)?\s*\n?", "", action_input)
                action_input = re.sub(r"\n?```\s*$", "", action_input)

    # Extract Final Answer if present
    final_match = re.search(r"Final Answer:\s*(.+?)$", text, re.DOTALL)
    if final_match:
        final_answer = final_match.group(1).strip()

    return thought, action, action_input, final_answer


async def execute_tool(action: str, action_input: str) -> str:
    """Execute the specified tool and return the result."""
    if action.lower() == "execute_sql":
        try:
            # Clean up the SQL query
            query = action_input.strip()
            if not query:
                return "Error: Empty SQL query"

            columns, rows = await execute_sql(query)

            if not rows:
                return "Query returned no results."

            # Format results as a readable table
            result_lines = []
            result_lines.append("| " + " | ".join(columns) + " |")
            result_lines.append("| " + " | ".join(["---"] * len(columns)) + " |")

            for row in rows[:50]:  # Limit to 50 rows
                formatted_cells = []
                for cell in row:
                    if cell is None:
                        formatted_cells.append("NULL")
                    elif isinstance(cell, str) and len(cell) > 100:
                        formatted_cells.append(cell[:100] + "...")
                    else:
                        formatted_cells.append(str(cell))
                result_lines.append("| " + " | ".join(formatted_cells) + " |")

            if len(rows) > 50:
                result_lines.append(f"\n... and {len(rows) - 50} more rows")

            result_lines.append(f"\nTotal: {len(rows)} row(s)")

            return "\n".join(result_lines)

        except ValueError as e:
            return f"Error: {str(e)}"
        except Exception as e:
            return f"SQL Error: {str(e)}"
    else:
        return f"Unknown action: {action}. Only 'execute_sql' is available."


async def run_chat_agent(user_message: str, conversation_history: list[dict] | None = None) -> ChatResponse:
    """Run the ReAct agent to answer a user's question about the database."""
    client = get_client()
    system_prompt = build_system_prompt()

    steps: list[AgentStep] = []
    has_queried = False  # Track if any SQL queries have been executed

    # Build the conversation for the LLM
    messages = [system_prompt]

    # Add conversation history if provided
    if conversation_history:
        for msg in conversation_history[-6:]:  # Keep last 6 messages for context
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                messages.append(f"User: {content}")
            else:
                messages.append(f"Assistant: {content}")

    messages.append(f"User: {user_message}")

    current_prompt = "\n\n".join(messages)

    for iteration in range(MAX_ITERATIONS):
        try:
            # Call the LLM
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=current_prompt,
            )

            response_text = response.text
            logger.info(f"Agent response (iteration {iteration + 1}):\n{response_text}")

            # Parse the response
            thought, action, action_input, final_answer = parse_agent_response(response_text)

            step = AgentStep(thought=thought or "")

            # Decide what to do based on what was parsed and current state
            # Priority: If we've already queried and have a final answer, use it
            #           Otherwise, if there's an action, execute it
            #           Otherwise, if there's a final answer but no query yet, reject it

            if has_queried and final_answer:
                # We have query results and a final answer - accept it
                step.thought = thought or "Providing final answer"
                steps.append(step)
                return ChatResponse(answer=final_answer, steps=steps)

            if action and action_input:
                step.action = action
                step.action_input = action_input

                # Execute the tool
                observation = await execute_tool(action, action_input)
                step.observation = observation
                steps.append(step)
                has_queried = True  # Mark that we've executed a query
                logger.info(f"Executed SQL query: {action_input}")

                # Add the observation to the prompt for the next iteration
                current_prompt += f"\n\n{response_text}\n\nObservation: {observation}"
            elif final_answer and not has_queried:
                # Has final answer but hasn't queried - reject and force a query
                logger.warning("LLM tried to answer without querying - forcing a query")
                steps.append(step)
                current_prompt += f"\n\n{response_text}\n\nYou must query the database first before providing an answer. You have NO knowledge of the data. Use execute_sql to query, then answer based on the results."
            else:
                # No action and no final answer - force a query
                steps.append(step)
                current_prompt += f"\n\n{response_text}\n\nYou must use execute_sql to query the database. Provide:\nThought: [what you need to find]\nAction: execute_sql\nAction Input: [your SQL query]"

        except Exception as e:
            logger.error(f"Error in agent iteration {iteration + 1}: {e}", exc_info=True)
            return ChatResponse(
                answer="I encountered an error while processing your request.",
                steps=steps,
                error=str(e)
            )

    # Max iterations reached
    return ChatResponse(
        answer="I wasn't able to find a complete answer. Here's what I learned:\n\n" +
               "\n".join(f"- {step.thought}" for step in steps if step.thought),
        steps=steps,
        error="Maximum reasoning steps reached"
    )
