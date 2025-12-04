from mcp.server.fastmcp import FastMCP
from .mcp_client import InnerMCPClient
from .masking import mask_json
import os
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("proxy-opensearch")

# Inner MCP Server Configuration
# We assume the user has 'uv' installed and 'opensearch-mcp-server-py' is available via uvx
# Or they can set INNER_MCP_CMD environment variable
INNER_CMD_STR = os.environ.get("INNER_MCP_CMD", "uvx opensearch-mcp-server-py")
INNER_CMD = INNER_CMD_STR.split()

if INNER_CMD[0] == "python":
    INNER_CMD[0] = sys.executable

# Force unbuffered output if using python
if INNER_CMD[0] == sys.executable and "-u" not in INNER_CMD:
    INNER_CMD.insert(1, "-u")

# Initialize the client to talk to the real OpenSearch MCP
try:
    inner_client = InnerMCPClient(INNER_CMD)
except Exception as e:
    logger.error(f"Failed to initialize inner client: {e}")
    inner_client = None

@mcp.tool()
def search_index_masked(
    index: str,
    query: dict = None,
) -> dict:
    """
    Search an OpenSearch index and return masked results.
    Proxies to the 'SearchIndexTool' of the inner OpenSearch MCP server.
    
    Args:
        index: The name of the index to search.
        query: The OpenSearch Query DSL query. Defaults to {"match_all": {}}.
    """
    if not inner_client:
        return {"error": "Inner MCP server is not running."}

    # Default to match_all if no query provided
    if query is None:
        query = {"query": {"match_all": {}}}

    # Construct arguments for the inner tool
    # SearchIndexTool expects 'index' and 'query'
    inner_args = {
        "index": index,
        "query": query,
    }

    try:
        raw_result = inner_client.call_tool("SearchIndexTool", inner_args)
        
        # Mask the results
        masked_result = mask_json(raw_result)
        return masked_result
    except Exception as e:
        return {"error": f"Failed to search and mask: {str(e)}"}

@mcp.tool()
def list_indices() -> dict:
    """
    List indices in the OpenSearch cluster.
    Proxies to 'ListIndexTool'.
    """
    if not inner_client:
        return {"error": "Inner MCP server is not running."}

    try:
        # ListIndexTool takes optional 'index' and 'include_detail'
        return inner_client.call_tool("ListIndexTool", {})
    except Exception as e:
        return {"error": f"Failed to list indices: {str(e)}"}

@mcp.tool()
def get_index_mapping(
    index: str
) -> dict:
    """
    Get mapping for an index.
    Proxies to 'IndexMappingTool'.
    """
    if not inner_client:
        return {"error": "Inner MCP server is not running."}

    inner_args = {"index": index}

    try:
        return inner_client.call_tool("IndexMappingTool", inner_args)
    except Exception as e:
        return {"error": f"Failed to get mapping: {str(e)}"}

def main():
    mcp.run()

if __name__ == "__main__":
    main()
