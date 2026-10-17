"use client";

import React from "react";
import { ClauseModel } from "@/types";
import { FileCode, CheckCircle2, Bookmark } from "lucide-react";

interface TextViewerProps {
  clauses: ClauseModel[];
  selectedClauseId: string | null;
  onSelectClause?: (clauseId: string) => void;
  selectedFindingQuote?: string | null;
}

export default function TextViewer({
  clauses,
  selectedClauseId,
  onSelectClause,
  selectedFindingQuote,
}: TextViewerProps) {
  return (
    <div className="flex flex-col h-full bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden shadow-2xl">
      {/* Header Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 text-xs text-zinc-300 select-none">
        <div className="flex items-center gap-2 font-medium text-zinc-200">
          <FileCode className="w-4 h-4 text-cyan-400" />
          <span>Document Clause Viewer</span>
          <span className="text-zinc-500 font-normal">
            ({clauses.length} {clauses.length === 1 ? "clause" : "clauses"})
          </span>
        </div>

        {selectedClauseId && (
          <div className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-full text-xs font-semibold animate-pulse">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
            <span>Clause {selectedClauseId} Highlighted</span>
          </div>
        )}
      </div>

      {/* Scrollable Clauses Panel */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-zinc-950/80 custom-scrollbar">
        {clauses.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-80 text-zinc-400 text-sm text-center p-6 space-y-3">
            <div className="w-12 h-12 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-500">
              <FileCode className="w-6 h-6 opacity-60" />
            </div>
            <div>
              <p className="font-semibold text-zinc-200">No Clauses Detected</p>
              <p className="text-xs text-zinc-400 max-w-sm mt-1 leading-relaxed">
                The submitted text could not be segmented into standard contract clauses. Please ensure the text includes numbered sections (e.g., &ldquo;1. Acceptance&rdquo;, &ldquo;Section 2&rdquo;) or distinct paragraph blocks.
              </p>
            </div>
          </div>
        ) : (
          clauses.map((clause) => {
            const isSelected = selectedClauseId === clause.id;

            // Highlight finding quote if this is the selected clause
            let renderedText: React.ReactNode = clause.text;
            if (
              isSelected &&
              selectedFindingQuote &&
              clause.text.includes(selectedFindingQuote.trim())
            ) {
              const cleanQuote = selectedFindingQuote.trim();
              const idx = clause.text.indexOf(cleanQuote);
              const before = clause.text.slice(0, idx);
              const after = clause.text.slice(idx + cleanQuote.length);
              renderedText = (
                <>
                  {before}
                  <mark className="bg-amber-400/30 text-amber-100 px-1 py-0.5 rounded border border-amber-400/40 font-medium">
                    {cleanQuote}
                  </mark>
                  {after}
                </>
              );
            }

            return (
              <div
                key={clause.id}
                id={`clause-${clause.id}`}
                onClick={() => onSelectClause?.(clause.id)}
                className={`p-4 rounded-xl border transition-all duration-300 cursor-pointer ${
                  isSelected
                    ? "bg-amber-950/20 border-amber-500/70 ring-2 ring-amber-400/40 shadow-lg shadow-amber-500/10"
                    : "bg-zinc-900/50 border-zinc-800/80 hover:border-zinc-700/80 hover:bg-zinc-900/80"
                }`}
              >
                {/* Clause Header */}
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={`px-2 py-0.5 text-xs font-mono font-bold rounded ${
                        isSelected
                          ? "bg-amber-500 text-zinc-950"
                          : "bg-zinc-800 text-zinc-300 border border-zinc-700"
                      }`}
                    >
                      {clause.id}
                    </span>
                    {(clause.heading || clause.label) && (
                      <span className="text-xs font-semibold text-zinc-200">
                        {clause.heading || clause.label}
                      </span>
                    )}
                  </div>

                  {isSelected ? (
                    <span className="flex items-center gap-1 text-[11px] font-semibold text-amber-400">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Active Citation
                    </span>
                  ) : (
                    <span className="text-[11px] text-zinc-500">
                      Clause #{clause.ordinal}
                    </span>
                  )}
                </div>

                {/* Clause Content */}
                <p className="text-xs text-zinc-300 leading-relaxed whitespace-pre-wrap font-sans">
                  {renderedText}
                </p>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
