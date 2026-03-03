"""Mutation operator: broaden exception handler types to Exception."""

from collections.abc import Iterable

import libcst as cst
import libcst.matchers as m

ALREADY_BROAD = {"Exception", "BaseException"}


def operator_exception_type_broadening(node: cst.ExceptHandler) -> Iterable[cst.ExceptHandler]:
    """Broaden specific exception types to Exception.

    except ValueError -> except Exception
    except (ValueError, KeyError) -> except Exception (replace entire tuple)
    except (ValueError, KeyError) -> except (Exception, KeyError) and except (ValueError, Exception)

    Skip: bare except, except Exception, except BaseException.
    """
    if node.type is None:
        return

    exc_type = node.type

    # Simple name: except ValueError -> except Exception
    if isinstance(exc_type, cst.Name):
        if exc_type.value in ALREADY_BROAD:
            return
        yield node.with_changes(type=cst.Name("Exception"))
        return

    # Tuple: except (ValueError, KeyError) -> various
    if isinstance(exc_type, cst.Tuple):
        elements = exc_type.elements
        if len(elements) < 2:
            return

        # Yield: replace entire tuple with just Exception
        yield node.with_changes(type=cst.Name("Exception"))

        # Yield: replace each individual type with Exception (if not already)
        for i, elem in enumerate(elements):
            if isinstance(elem.value, cst.Name) and elem.value.value in ALREADY_BROAD:
                continue
            new_elem = elem.with_changes(value=cst.Name("Exception"))
            new_elements = list(elements)
            new_elements[i] = new_elem
            yield node.with_changes(type=exc_type.with_changes(elements=new_elements))


operators = [(cst.ExceptHandler, operator_exception_type_broadening)]
