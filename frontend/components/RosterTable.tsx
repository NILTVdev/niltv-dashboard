"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
// v9 migration: the /legacy entry point is TanStack's official v8-compat
// layer (same options shape, ColumnDef arity, get*RowModel stubs). New
// tables should use the v9-native useTable + features API instead.
import {
  useLegacyTable,
  getCoreRowModel,
  getSortedRowModel,
  getFilteredRowModel,
  type LegacyColumnDef,
} from "@tanstack/react-table/legacy";
import { flexRender, type SortingState } from "@tanstack/react-table";
import { ChevronUp, ChevronDown, ChevronsUpDown } from "lucide-react";
import { fmt } from "@/lib/utils";
import type { Athlete } from "@/lib/types";

interface Props {
  athletes: Athlete[];
  sports: string[];
}

export default function RosterTable({ athletes, sports }: Props) {
  const [sorting, setSorting] = useState<SortingState>([
    { id: "social_valuation", desc: true },
  ]);
  const [sport, setSport] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    return athletes.filter((a) => {
      if (sport !== "all" && a.sport !== sport) return false;
      if (search) {
        const q = search.toLowerCase();
        return (
          a.name.toLowerCase().includes(q) ||
          a.ig_handle?.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [athletes, sport, search]);

  const columns = useMemo<LegacyColumnDef<Athlete>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: ({ row }) => (
          <Link
            href={`/athletes/${row.original.id}`}
            className="font-medium text-[var(--brand)] hover:underline"
          >
            {row.original.name}
          </Link>
        ),
      },
      {
        accessorKey: "sport",
        header: "Sport",
        cell: ({ getValue }) => (
          <span className="text-sm text-[#64748b]">{getValue() as string ?? "—"}</span>
        ),
      },
      {
        accessorKey: "ig_handle",
        header: "Instagram",
        cell: ({ getValue }) => {
          const h = getValue() as string | null;
          if (!h) return <span className="text-[#cbd5e1]">—</span>;
          return (
            <a
              href={`https://instagram.com/${h}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-sm text-[var(--brand)] hover:underline"
            >
              @{h}
            </a>
          );
        },
        enableSorting: false,
      },
      {
        accessorKey: "ig_followers",
        header: "IG Followers",
        cell: ({ getValue }) => (
          <span className="text-sm tabular-nums">{fmt(getValue() as number | null)}</span>
        ),
      },
      {
        accessorKey: "social_valuation",
        header: "Social Valuation",
        cell: ({ getValue }) => (
          <span className="text-sm tabular-nums">{fmt(getValue() as number | null)}</span>
        ),
      },
    ],
    []
  );

  const table = useLegacyTable({
    data: filtered,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
  });

  const totalFollowers = useMemo(
    () => filtered.reduce((s, a) => s + (a.ig_followers ?? 0), 0),
    [filtered]
  );

  const totalValuation = useMemo(
    () => filtered.reduce((s, a) => s + (a.social_valuation ?? 0), 0),
    [filtered]
  );

  return (
    <div className="space-y-4">
      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Athletes", value: filtered.length.toLocaleString() },
          { label: "Total IG Followers", value: fmt(totalFollowers) },
          {
            label: "Median IG Followers",
            value: fmt(
              (() => {
                const vals = filtered
                  .map((a) => a.ig_followers)
                  .filter((v): v is number => v != null)
                  .sort((a, b) => a - b);
                if (!vals.length) return null;
                const mid = Math.floor(vals.length / 2);
                return vals.length % 2 ? vals[mid] : Math.round((vals[mid - 1] + vals[mid]) / 2);
              })()
            ),
          },
          { label: "Total Social Valuation", value: fmt(totalValuation) },
        ].map((k) => (
          <div
            key={k.label}
            className="bg-white rounded-xl border border-[#e2e8f0] p-4 shadow-sm"
          >
            <p className="text-xs text-[#64748b] mb-1">{k.label}</p>
            <p className="text-2xl font-bold text-[var(--brand)]">{k.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <select
          value={sport}
          onChange={(e) => setSport(e.target.value)}
          className="px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)]"
        >
          <option value="all">All Sports</option>
          {sports.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search name or handle…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="px-3 py-2 rounded-lg border border-[#e2e8f0] text-sm bg-white focus:outline-none focus:ring-2 focus:ring-[var(--brand)] w-64"
        />
      </div>

      {/* Table */}
      <div className="bg-white rounded-xl border border-[#e2e8f0] shadow-sm overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            {table.getHeaderGroups().map((hg) => (
              <tr key={hg.id} className="border-b border-[#e2e8f0]">
                {hg.headers.map((header) => (
                  <th
                    key={header.id}
                    onClick={header.column.getToggleSortingHandler()}
                    className="px-4 py-3 text-left text-xs font-semibold text-[#64748b] uppercase tracking-wide whitespace-nowrap"
                    style={{ cursor: header.column.getCanSort() ? "pointer" : "default" }}
                  >
                    <span className="flex items-center gap-1">
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getCanSort() &&
                        ({
                          asc: <ChevronUp size={12} />,
                          desc: <ChevronDown size={12} />,
                        }[header.column.getIsSorted() as string] ?? (
                          <ChevronsUpDown size={12} className="opacity-40" />
                        ))}
                    </span>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-[#f1f5f9] last:border-0 hover:bg-[#f8fafc] transition-colors"
              >
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-4 py-3 whitespace-nowrap">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
            {table.getRowModel().rows.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-[#94a3b8]">
                  No athletes found.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-[#94a3b8]">
        Showing {filtered.length} of {athletes.length} athletes
      </p>
    </div>
  );
}
