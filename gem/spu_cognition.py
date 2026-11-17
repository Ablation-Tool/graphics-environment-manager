from __future__ import annotations

from collections import Counter
import hashlib
import math

from .imagery import dijkstra

TIMING = {
    "a": (0, 2), "sf": (0, 2), "ai": (0, 2), "ahi": (0, 2),
    "and": (0, 2), "or": (0, 2), "xor": (0, 2), "nand": (0, 2), "nor": (0, 2),
    "andbi": (0, 2), "andhi": (0, 2), "andi": (0, 2),
    "orbi": (0, 2), "orhi": (0, 2), "ori": (0, 2),
    "xorbi": (0, 2), "xorhi": (0, 2), "xori": (0, 2),
    "il": (0, 2), "ilh": (0, 2), "ilhu": (0, 2), "ila": (0, 2), "iohl": (0, 2),
    "lqd": (1, 6), "stqd": (1, 6), "lqr": (1, 6), "stqr": (1, 6),
    "lqa": (1, 6), "stqa": (1, 6), "lqx": (1, 6), "stqx": (1, 6),
    "bi": (1, 4), "br": (1, 4), "bra": (1, 4), "brasl": (1, 4), "brsl": (1, 4),
    "brz": (1, 4), "brnz": (1, 4), "brhz": (1, 4), "brhnz": (1, 4),
    "cbd": (1, 4), "cbx": (1, 4), "cdd": (1, 4), "cdx": (1, 4),
    "chd": (1, 4), "chx": (1, 4), "cwd": (1, 4), "cwx": (1, 4),
    "fsm": (1, 4), "fsmb": (1, 4), "fsmbi": (1, 4), "fsmh": (1, 4),
    "fa": (0, 6), "fm": (0, 6), "fma": (0, 6), "fms": (0, 6), "fnms": (0, 6),
    "mpy": (0, 7), "mpyu": (0, 7), "mpyi": (0, 7), "mpyui": (0, 7), "mpya": (0, 7),
    "mpyh": (0, 7), "mpyhh": (0, 7), "mpyhha": (0, 7), "mpyhhu": (0, 7), "mpyhhau": (0, 7),
    "selb": (0, 2), "shufb": (1, 4), "lnop": (1, 0), "nop": (0, 2),
    "shlqbyi": (1, 4), "shlqby": (1, 4), "shlqbybi": (1, 4), "rotqbyi": (1, 4),
}
BRANCH_RELATIVE = {"br", "brsl", "brz", "brnz", "brhz", "brhnz"}
BRANCH_ABSOLUTE = {"bra", "brasl"}
NO_WRITE = {"nop", "lnop", "stop", "stopd", "sync", "dsync", "bi", "bid", "bie", "br", "bra", "brz", "brnz", "brhz", "brhnz", "stqd", "stqr", "stqa", "stqx"}


def _api():
    try:
        from modules.spu_disassembler import decode_spu_word, disassemble_spu_text, extract_spu_text_from_elf
    except ImportError as error:
        raise ValueError("SPU cognition requires Ablation's modules.spu_disassembler") from error
    return decode_spu_word, disassemble_spu_text, extract_spu_text_from_elf


def local_store_address(immediate, register_value, limit=0x3FFFF):
    if isinstance(immediate, bool) or not isinstance(immediate, int) or not -512 <= immediate <= 511:
        raise ValueError("lqd/stqd immediate must be a signed 10-bit value")
    if isinstance(register_value, bool) or not isinstance(register_value, int) or register_value < 0:
        raise ValueError("register value must be a nonnegative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("local storage limit must be positive")
    return (immediate * 16 + register_value) & limit & 0xFFFFFFF0


class LocalStore:
    def __init__(self, size=256 * 1024, initial=None):
        if isinstance(size, bool) or not isinstance(size, int) or size <= 0 or size > 256 * 1024:
            raise ValueError("local store size must be from 1 to 262144 bytes")
        self.data = bytearray(size)
        if initial is not None:
            if len(initial) > size:
                raise ValueError("initial local-store contents exceed capacity")
            self.data[:len(initial)] = initial

    def _check(self, address):
        if isinstance(address, bool) or not isinstance(address, int) or address < 0 or address + 16 > len(self.data):
            raise ValueError("quadword access is outside local storage")

    def read_quadword(self, address):
        self._check(address)
        return bytes(self.data[address:address + 16])

    def write_quadword(self, address, value):
        self._check(address)
        if not isinstance(value, (bytes, bytearray, memoryview)) or len(value) != 16:
            raise ValueError("quadword writes require exactly 16 bytes")
        self.data[address:address + 16] = value


def _record(instruction):
    return {
        "addr": instruction.addr,
        "word": instruction.word,
        "mnemonic": instruction.mnemonic,
        "fmt": instruction.fmt,
        "rT": instruction.rT,
        "rA": instruction.rA,
        "rB": instruction.rB,
        "I7": instruction.I7,
        "I10": instruction.I10,
        "I16": instruction.I16,
        "I18": instruction.I18,
    }


class SPUExecutionField:
    def __init__(self, instructions, entry, text, source):
        self.instructions = [_record(instruction) for instruction in instructions]
        if not self.instructions:
            raise ValueError("SPU execution field requires at least one instruction")
        self.entry = entry
        self.text = text
        self.source = source
        self.by_address = {instruction["addr"]: instruction for instruction in self.instructions}
        if len(self.by_address) != len(self.instructions):
            raise ValueError("SPU instruction addresses must be unique")

    @classmethod
    def from_elf(cls, data, source="SPU ELF artifact"):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise ValueError("SPU ELF input must be bytes")
        data = bytes(data)
        _decode, disassemble, extract = _api()
        text, base, entry = extract(data)
        instructions = list(disassemble(text, base_vaddr=base))
        return cls(instructions, entry, text, {
            "kind": "spu_elf",
            "description": source,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "text_sha256": hashlib.sha256(text).hexdigest(),
        })

    @classmethod
    def from_words(cls, words, source="declared instruction words"):
        decode, _disassemble, _extract = _api()
        instructions = [decode(addr, word) for addr, word in words]
        text = b"".join(word.to_bytes(4, "big") for _addr, word in words)
        return cls(instructions, words[0][0], text, {
            "kind": "instruction_words",
            "description": source,
            "sha256": hashlib.sha256(text).hexdigest(),
            "bytes": len(text),
            "text_sha256": hashlib.sha256(text).hexdigest(),
        })

    def _branch_target(self, instruction):
        mnemonic = instruction["mnemonic"]
        if mnemonic in BRANCH_RELATIVE:
            return instruction["addr"] + instruction["I16"] * 4
        if mnemonic in BRANCH_ABSOLUTE:
            return instruction["I16"] * 4
        return None

    def graph(self):
        edges = {}
        ordered = sorted(self.instructions, key=lambda item: item["addr"])
        for index, instruction in enumerate(ordered):
            source = instruction["addr"]
            if index + 1 < len(ordered):
                target = ordered[index + 1]["addr"]
                latency = TIMING.get(instruction["mnemonic"], (None, 1))[1]
                edges[source, target] = float(latency)
            target = self._branch_target(instruction)
            if target in self.by_address:
                latency = TIMING.get(instruction["mnemonic"], (None, 1))[1]
                edges[source, target] = float(latency)
        return edges

    def execution_path(self, target=None):
        target = self.instructions[-1]["addr"] if target is None else target
        route = dijkstra(sorted(self.by_address), self.graph(), self.entry, target)
        return {
            **route,
            "entry": self.entry,
            "target": target,
            "scope": "minimum cumulative instruction-latency path through decoded sequential and direct-branch edges; unknown latencies use one declared placeholder cycle",
        }

    def schedule(self, limit=None):
        ordered = sorted(self.instructions, key=lambda item: item["addr"])
        if limit is not None:
            ordered = ordered[:limit]
        available = {0: 0, 1: 0}
        register_ready = {}
        current = 0
        records = []
        index = 0
        while index < len(ordered):
            first = ordered[index]
            pipeline, latency = TIMING.get(first["mnemonic"], (None, 1))
            if pipeline is None:
                records.append({"addr": first["addr"], "mnemonic": first["mnemonic"], "pipeline": None, "latency": None, "timing_status": "unknown"})
                index += 1
                continue
            reads = [first[key] for key in ("rA", "rB") if first["fmt"] in {"rr", "rrr"}]
            dependency = max([register_ready.get(register, 0) for register in reads] + [0])
            start = max(current, available[pipeline], dependency)
            dual = None
            if index + 1 < len(ordered):
                candidate = ordered[index + 1]
                candidate_pipeline, candidate_latency = TIMING.get(candidate["mnemonic"], (None, 1))
                if pipeline == 0 and candidate_pipeline == 1:
                    candidate_reads = [candidate[key] for key in ("rA", "rB") if candidate["fmt"] in {"rr", "rrr"}]
                    candidate_dependency = max([register_ready.get(register, 0) for register in candidate_reads] + [0])
                    dual_start = max(start, available[candidate_pipeline], candidate_dependency)
                    dual = (candidate, candidate_latency, dual_start)
            if dual is not None:
                candidate, candidate_latency, dual_start = dual
                records.append({"addr": first["addr"], "mnemonic": first["mnemonic"], "pipeline": pipeline, "latency": latency, "start": dual_start, "issue": "dual", "timing_status": "reference"})
                records.append({"addr": candidate["addr"], "mnemonic": candidate["mnemonic"], "pipeline": candidate_pipeline, "latency": candidate_latency, "start": dual_start, "issue": "dual", "timing_status": "reference"})
                available[pipeline] = dual_start + latency
                available[candidate_pipeline] = dual_start + candidate_latency
                if first["mnemonic"] not in NO_WRITE:
                    register_ready[first["rT"]] = dual_start + latency
                if candidate["mnemonic"] not in NO_WRITE:
                    register_ready[candidate["rT"]] = dual_start + candidate_latency
                current = dual_start + 1
                index += 2
            else:
                records.append({"addr": first["addr"], "mnemonic": first["mnemonic"], "pipeline": pipeline, "latency": latency, "start": start, "issue": "single", "timing_status": "reference"})
                available[pipeline] = start + latency
                if first["mnemonic"] not in NO_WRITE:
                    register_ready[first["rT"]] = start + latency
                current = start + 1
                index += 1
        return records

    def report(self):
        counts = Counter(instruction["mnemonic"] for instruction in self.instructions)
        known = sum(instruction["mnemonic"] in TIMING for instruction in self.instructions)
        schedule = self.schedule(limit=96)
        path = self.execution_path()
        return {
            "source": self.source,
            "entry": self.entry,
            "instruction_count": len(self.instructions),
            "text_bytes": len(self.text),
            "mnemonic_counts": dict(sorted(counts.items())),
            "timing": {
                "reference": "Programming the Cell Processor, Appendix D; SPU ISA v1.2 for instruction semantics",
                "known_instruction_count": known,
                "unknown_instruction_count": len(self.instructions) - known,
                "known_ratio": known / len(self.instructions),
                "unknown_latency_placeholder_cycles": 1,
                "scope": "program-order latency and dual-issue projection with register-read/write dependency approximation; not a hardware trace or complete channel/branch model",
            },
            "execution_imagery": {
                "path": path,
                "schedule_preview": schedule,
                "preview_instruction_limit": 96,
            },
            "provenance": "decoded observation; schedule and path are imagined projections, not observed execution",
        }
