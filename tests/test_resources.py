import pytest
from pathlib import Path
from bin import resources


def test_parse_resource_node_returns_dataclass():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
description: "TCP port 8080"
```
"""
    nodes = resources.parse_resources(md)
    assert len(nodes) == 1


def test_parse_resource_node_has_id():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
description: "TCP port 8080"
```
"""
    nodes = resources.parse_resources(md)
    assert nodes[0].id == "res-port-8080"


def test_parse_resource_node_has_kind():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
description: "TCP port 8080"
```
"""
    nodes = resources.parse_resources(md)
    assert nodes[0].kind == "port"


def test_parse_resource_node_has_identifier():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
description: "TCP port 8080"
```
"""
    nodes = resources.parse_resources(md)
    assert nodes[0].identifier == "8080"


def test_parse_resource_node_has_capacity():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
description: "TCP port 8080"
```
"""
    nodes = resources.parse_resources(md)
    assert nodes[0].capacity == 1


def test_parse_resource_kind_must_be_known():
    md = """## Resource: bogus

```yaml
id: res-bogus
kind: telepathy
identifier: "x"
capacity: 1
```
"""
    with pytest.raises(ValueError, match="unknown resource kind"):
        resources.parse_resources(md)


def test_parse_resource_capacity_must_be_positive_int():
    md = """## Resource: port:0

```yaml
id: res-zero
kind: port
identifier: "0"
capacity: 0
```
"""
    with pytest.raises(ValueError, match="capacity"):
        resources.parse_resources(md)


def test_parse_multiple_resources():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
```

## Resource: db:primary

```yaml
id: res-db-primary
kind: db_connection
identifier: "postgres://localhost/primary"
capacity: 5
```
"""
    nodes = resources.parse_resources(md)
    assert len(nodes) == 2


def test_parse_multiple_resources_have_correct_kinds():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
```

## Resource: db:primary

```yaml
id: res-db-primary
kind: db_connection
identifier: "postgres://localhost/primary"
capacity: 5
```
"""
    nodes = resources.parse_resources(md)
    assert {n.kind for n in nodes} == {"port", "db_connection"}


def test_resource_id_unique_check():
    md = """## Resource: port:8080

```yaml
id: res-port-8080
kind: port
identifier: "8080"
capacity: 1
```

## Resource: port:dup

```yaml
id: res-port-8080
kind: port
identifier: "9090"
capacity: 1
```
"""
    with pytest.raises(ValueError, match="duplicate"):
        resources.parse_resources(md)


def test_extract_resources_from_action_port_pattern():
    cmd = "python3 -m http.server 8080"
    found = resources.extract_resources_from_action(cmd)
    assert any(r.kind == "port" and r.identifier == "8080" for r in found)


def test_extract_resources_from_action_no_match_returns_empty():
    found = resources.extract_resources_from_action("ls -la")
    assert found == []


def test_extract_resources_from_action_skips_quoted_port():
    # Same defense as tier.py: don't fire on echoed text
    cmd = 'git commit -m "fix port 8080 bug"'
    found = resources.extract_resources_from_action(cmd)
    assert found == []
