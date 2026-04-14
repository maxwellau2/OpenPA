from typing import List
from fastmcp import FastMCP

mcp = FastMCP("mcp_sort")

@mcp.tool()
def sort_numbers(_user_id: str, numbers: List[float], order: str = "ascending") -> List[float]:
    """
    Sorts a list of numbers in ascending or descending order.

    Args:
        _user_id: User ID (injected automatically)
        numbers: A list of numbers to be sorted.
        order: The sort order, either "ascending" or "descending". Defaults to "ascending".

    Returns:
        A new list containing the sorted numbers.
    """
    if not all(isinstance(n, (int, float)) for n in numbers):
        raise ValueError("All elements in 'numbers' must be integers or floats.")

    if order == "ascending":
        return sorted(numbers)
    elif order == "descending":
        return sorted(numbers, reverse=True)
    else:
        raise ValueError("Invalid order. Must be 'ascending' or 'descending'.")
