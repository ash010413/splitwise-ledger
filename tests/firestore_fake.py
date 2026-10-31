"""Small transaction fake. Live Firestore is checked separately before deployment."""

import copy
import uuid


class Snapshot:
    def __init__(self, ref, value):
        self.id, self.exists, self.value = ref.id, value is not None, copy.deepcopy(value)

    def to_dict(self):
        return copy.deepcopy(self.value)


class Reference:
    def __init__(self, db, path):
        self.db, self.path, self.id = db, path, path.split("/")[-1]

    def collection(self, name):
        return Collection(self.db, self.path + "/" + name)

    def get(self, transaction=None):
        return Snapshot(self, self.db.data.get(self.path))

    def create(self, value):
        assert self.path not in self.db.data
        self.set(value)

    def set(self, value):
        self.db.data[self.path] = copy.deepcopy(value)

    def delete(self):
        self.db.data.pop(self.path, None)


class Collection:
    def __init__(self, db, path):
        self.db, self.path = db, path

    def document(self, key):
        return Reference(self.db, self.path + "/" + str(key))

    def stream(self):
        return [
            Snapshot(Reference(self.db, p), v)
            for p, v in self.db.data.items()
            if p.rpartition("/")[0] == self.path
        ]


class Transaction:
    def __init__(self, db):
        self.db, self.writes = db, []

    def set(self, ref, value):
        self.writes.append(("set", ref, copy.deepcopy(value)))

    def update(self, ref, value):
        self.writes.append(("update", ref, copy.deepcopy(value)))

    def delete(self, ref):
        self.writes.append(("delete", ref, None))

    def run(self, fn):
        result = fn(self)
        for action, ref, value in self.writes:
            if action == "delete":
                ref.delete()
            elif action == "update":
                ref.set({**self.db.data[ref.path], **value})
            else:
                ref.set(value)
        return result


class Client:
    def __init__(self):
        self.data, self.project, self.reads = {}, uuid.uuid4().hex, 0

    def collection(self, name):
        return Collection(self, name)

    def transaction(self):
        return Transaction(self)

    def get_all(self, refs, transaction=None):
        self.reads += len(refs)
        return [ref.get(transaction=transaction) for ref in refs]
