import json
import subprocess
import threading
import logging
import os
import sys
import time
from concurrent.futures import Future, TimeoutError

logger = logging.getLogger(__name__)

class InnerMCPClient:
    """
    A client for interacting with an inner MCP server subprocess.
    
    This class handles the lifecycle of the subprocess, including starting it,
    initializing the MCP protocol, and sending requests.
    It includes a reader thread to handle responses asynchronously and supports timeouts.
    """
    def __init__(self, cmd, env=None, timeout=30):
        """
        Initialize the InnerMCPClient.

        Args:
            cmd (list): List of command arguments to start the subprocess.
            env (dict, optional): Environment variables for the subprocess.
            timeout (int): Default timeout for requests in seconds.
        """
        self.cmd = cmd
        self.env = env or os.environ.copy()
        self.timeout = timeout
        self.proc = None
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._pending_requests = {} # id -> Future
        self._reader_thread = None
        self._stop_event = threading.Event()
        
        self._start_subprocess()

    def _start_subprocess(self):
        """
        Starts the inner MCP server subprocess and initializes the connection.
        """
        try:
            logger.info(f"Starting inner MCP server: {self.cmd}")
            self.proc = subprocess.Popen(
                self.cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=sys.stderr, # Inherit stderr
                text=True,
                encoding='utf-8',
                env=self.env
            )
            
            # Start reader thread
            self._stop_event.clear()
            self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
            self._reader_thread.start()
            
            self._initialize()
        except Exception as e:
            logger.error(f"Failed to start inner MCP server: {e}")
            raise

    def _restart_subprocess(self):
        """
        Kills and restarts the subprocess.
        """
        logger.warning("Restarting inner MCP server...")
        self._stop_event.set()
        if self.proc:
            try:
                self.proc.terminate()
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()
        
        # Cancel all pending requests
        with self._write_lock: # Reuse write lock or just do it?
            # It's better to just clear them. The futures will be cancelled.
            for req_id, future in self._pending_requests.items():
                if not future.done():
                    future.set_exception(RuntimeError("Server restarted"))
            self._pending_requests.clear()

        self._start_subprocess()

    def _reader_loop(self):
        """
        Reads lines from stdout and resolves pending requests.
        """
        while not self._stop_event.is_set():
            try:
                if not self.proc or not self.proc.stdout:
                    break
                
                line = self.proc.stdout.readline()
                if not line:
                    logger.info("Inner server stdout closed")
                    break
                
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"Received invalid JSON: {line.strip()}")
                    continue
                
                # Handle response
                req_id = resp.get("id")
                if req_id is not None:
                    future = self._pending_requests.pop(req_id, None)
                    if future and not future.done():
                        if "error" in resp:
                            future.set_exception(RuntimeError(f"Inner MCP error: {resp['error']}"))
                        else:
                            future.set_result(resp.get("result", {}))
                
                # Handle notifications (optional, currently ignored or logged)
                if "method" in resp and "id" not in resp:
                    logger.debug(f"Received notification: {resp['method']}")

            except Exception as e:
                logger.error(f"Error in reader loop: {e}")
                break

    def _initialize(self):
        """
        Performs the MCP initialization handshake.
        """
        try:
            # Send initialize request
            # We use a longer timeout for initialization just in case
            init_result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "proxy-client", "version": "1.0"}
            }, timeout=60)
            
            # Send initialized notification
            notify = {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {}
            }
            with self._write_lock:
                self.proc.stdin.write(json.dumps(notify) + "\n")
                self.proc.stdin.flush()
            
            logger.info("Inner MCP server initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize inner MCP server: {e}")
            raise

    def _get_id(self):
        with self._write_lock:
            i = self._next_id
            self._next_id += 1
            return i

    def _send_request(self, method: str, params: dict, timeout=None) -> dict:
        """
        Sends a JSON-RPC request to the inner server and waits for the response.
        """
        if timeout is None:
            timeout = self.timeout

        if self.proc.poll() is not None:
            logger.warning("Inner process died, restarting...")
            self._restart_subprocess()

        req_id = self._get_id()
        future = Future()
        self._pending_requests[req_id] = future
        
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        
        try:
            with self._write_lock:
                line = json.dumps(request) + "\n"
                self.proc.stdin.write(line)
                self.proc.stdin.flush()
            
            logger.debug(f"Sent request {req_id}: {method}")
            
            # Wait for result
            return future.result(timeout=timeout)
            
        except TimeoutError:
            logger.error(f"Request {req_id} ({method}) timed out after {timeout}s")
            # Remove future to prevent memory leak if it eventually comes back
            self._pending_requests.pop(req_id, None)
            # Restart server to clear stuck state
            self._restart_subprocess()
            raise TimeoutError(f"Request {method} timed out")
            
        except Exception as e:
            logger.error(f"Error calling method {method}: {e}")
            self._pending_requests.pop(req_id, None)
            raise

    def call_tool(self, tool_name: str, args: dict, timeout=None):
        """
        Sends a tool call request to the inner MCP server.
        """
        return self._send_request("tools/call", {
            "name": tool_name,
            "arguments": args,
        }, timeout=timeout)
