import json
import os
import sys
import logging
from typing import Dict, Any, List
from proxy_mcp.mcp_client import InnerMCPClient
try:
    from openai import OpenAI
except ImportError:
    print("Error: 'openai' package is not installed. Please install it using 'pip install openai'")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_config(config_path: str) -> Dict[str, Any]:
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        logger.error(f"Config file not found at {config_path}")
        sys.exit(1)
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in config file at {config_path}")
        sys.exit(1)

def mcp_tool_to_openai_function(tool: Dict[str, Any]) -> Dict[str, Any]:
    """
    Converts an MCP tool definition to an OpenAI function definition.
    """
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {})
        }
    }

class InteractiveClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.openai_client = OpenAI(api_key=config.get("openaiKey"))
        self.servers: Dict[str, InnerMCPClient] = {}
        self.tools: List[Dict[str, Any]] = []
        self.tool_map: Dict[str, Any] = {} # Map tool name to (server_name, tool_def)

    def start_servers(self):
        mcp_servers = self.config.get("mcpServers", {})
        for name, server_config in mcp_servers.items():
            try:
                cmd = [server_config["command"]] + server_config.get("args", [])
                env = os.environ.copy()
                env.update(server_config.get("env", {}))
                
                logger.info(f"Starting server '{name}'...")
                client = InnerMCPClient(cmd, env=env)
                self.servers[name] = client
                
                # Fetch tools
                response = client._send_request("tools/list", {})
                server_tools = response.get("tools", [])
                
                for tool in server_tools:
                    self.tools.append(mcp_tool_to_openai_function(tool))
                    self.tool_map[tool["name"]] = {"server": name, "def": tool}
                
                logger.info(f"Server '{name}' started with {len(server_tools)} tools.")
                
            except Exception as e:
                logger.error(f"Failed to start server '{name}': {e}")

    def process_message(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Process a message history and return the final AI response and any tool calls made.
        This handles the tool execution loop.
        """
        try:
            current_messages = list(messages)
            all_tool_calls = []
            
            logger.info(f"Sending to OpenAI...")
            
            while True:
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=current_messages,
                    tools=self.tools if self.tools else None,
                )
                
                message = response.choices[0].message
                current_messages.append(message)
                
                if message.tool_calls:
                    logger.info("\nAI is thinking (calling tools)...")
                    for tool_call in message.tool_calls:
                        tool_name = tool_call.function.name
                        tool_args = json.loads(tool_call.function.arguments)
                        
                        tool_record = {
                            "id": tool_call.id,
                            "name": tool_name,
                            "args": tool_args,
                            "result": None,
                            "error": None
                        }
                        
                        if tool_name in self.tool_map:
                            server_name = self.tool_map[tool_name]["server"]
                            client = self.servers[server_name]
                            
                            logger.info(f"  -> Calling {tool_name} on {server_name} with {tool_args}")
                            try:
                                result = client.call_tool(tool_name, tool_args)
                                tool_record["result"] = result
                                content = json.dumps(result)
                            except Exception as e:
                                tool_record["error"] = str(e)
                                content = f"Error: {str(e)}"
                                logger.error(f"  -> Error: {e}")
                        else:
                            tool_record["error"] = "Tool not found"
                            content = "Error: Tool not found"
                            logger.error(f"  -> Error: Tool {tool_name} not found")

                        all_tool_calls.append(tool_record)
                        
                        current_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": content
                        })
                else:
                    # Final response
                    logger.info(f"\nAI: {message.content}")
                    return {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": all_tool_calls
                    }
                            
        except Exception as e:
            logger.error(f"OpenAI Error: {e}")
            return {"error": str(e)}

    def chat_loop(self):
        print("\n=== MCP Interactive Client ===")
        print("Type 'quit' or 'exit' to stop.")
        
        messages = []
        
        while True:
            try:
                user_input = input("\nUser: ").strip()
                if user_input.lower() in ['quit', 'exit']:
                    break
                
                if not user_input:
                    continue

                messages.append({"role": "user", "content": user_input})
                
                result = self.process_message(messages)
                
                if "error" in result:
                    print(f"Error: {result['error']}")
                else:
                    # Update messages with the conversation that happened in process_message
                    # But process_message returns the final result and tool calls, 
                    # it doesn't return the full intermediate messages easily unless we change return type.
                    # For CLI, we just append the final assistant message.
                    # Note: This simplifies history (loses intermediate tool messages in history for next turn),
                    # but for this simple CLI it's okay. 
                    # Ideally process_message should return the new messages to append.
                    messages.append({"role": "assistant", "content": result["content"]})
                        
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"Error: {e}")

    def cleanup(self):
        for name, client in self.servers.items():
            print(f"Stopping server '{name}'...")
            pass

if __name__ == "__main__":
    config_path = "config.json"
    if len(sys.argv) > 1:
        config_path = sys.argv[1]
        
    config = load_config(config_path)
    client = InteractiveClient(config)
    
    try:
        client.start_servers()
        client.chat_loop()
    finally:
        client.cleanup()
