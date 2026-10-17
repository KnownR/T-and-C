"use client";

import React, { useState, useEffect, useRef } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import { ClauseModel } from "@/types";
import { ZoomIn, ZoomOut, RotateCcw, FileText, CheckCircle2 } from "lucide-react";

// Point to local worker copied into /public
if (typeof window !== "undefined") {
  pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
}

interface PdfViewerProps {
  file: File | string | ArrayBuffer | null;
  clauses: ClauseModel[];
  selectedClauseId: string | null;
  onSelectClause?: (clauseId: string) => void;
}

export default function PdfViewer({
  file,
  clauses,
  selectedClauseId,
  onSelectClause,
}: PdfViewerProps) {
  const [numPages, setNumPages] = useState<number | null>(null);
  const [pageDimensions, setPageDimensions] = useState<
    Record<number, { width: number; height: number }>
  >({});
  const [containerWidth, setContainerWidth] = useState<number>(600);
  const [scale, setScale] = useState<number>(1.0);
  const containerRef = useRef<HTMLDivElement>(null);

  // Measure container width responsively
  useEffect(() => {
    if (!containerRef.current) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        if (entry.contentRect.width > 0) {
          // Subtract padding
          setContainerWidth(Math.max(300, entry.contentRect.width - 32));
        }
      }
    });
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
  };

  const handlePageLoadSuccess = (
    pageNumber: number,
    page: { originalWidth: number; originalHeight: number }
  ) => {
    setPageDimensions((prev) => ({
      ...prev,
      [pageNumber]: {
        width: page.originalWidth,
        height: page.originalHeight,
      },
    }));
  };

  const targetWidth = Math.round(containerWidth * scale);

  return (
    <div className="flex flex-col h-full bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden shadow-2xl">
      {/* PDF Controls Toolbar */}
      <div className="flex items-center justify-between px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 text-xs text-zinc-300 select-none">
        <div className="flex items-center gap-2 font-medium text-zinc-200">
          <FileText className="w-4 h-4 text-emerald-400" />
          <span>PDF Document Viewer</span>
          {numPages && (
            <span className="text-zinc-500 font-normal">
              ({numPages} {numPages === 1 ? "page" : "pages"})
            </span>
          )}
        </div>

        <div className="flex items-center gap-3">
          {selectedClauseId && (
            <div className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded-full text-xs font-semibold animate-pulse">
              <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
              <span>Clause {selectedClauseId} Highlighted</span>
            </div>
          )}

          <div className="flex items-center bg-zinc-800 rounded-lg p-0.5 border border-zinc-700">
            <button
              onClick={() => setScale((s) => Math.max(0.6, s - 0.15))}
              className="p-1 hover:text-white hover:bg-zinc-700 rounded transition"
              title="Zoom out"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <span className="px-2 font-mono text-[11px] text-zinc-400 min-w-12 text-center">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={() => setScale((s) => Math.min(1.8, s + 0.15))}
              className="p-1 hover:text-white hover:bg-zinc-700 rounded transition"
              title="Zoom in"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => setScale(1.0)}
              className="p-1 hover:text-white hover:bg-zinc-700 rounded transition ml-1"
              title="Reset zoom"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Scrollable PDF Document Canvas */}
      <div
        ref={containerRef}
        className="flex-1 overflow-y-auto p-4 flex flex-col items-center bg-zinc-950/80 custom-scrollbar"
      >
        {!file ? (
          <div className="flex flex-col items-center justify-center h-80 text-zinc-500 text-sm">
            <FileText className="w-10 h-10 mb-2 opacity-40" />
            <p>No PDF file loaded.</p>
          </div>
        ) : (
          <Document
            file={file}
            onLoadSuccess={onDocumentLoadSuccess}
            loading={
              <div className="flex flex-col items-center justify-center h-80 text-zinc-400 text-sm gap-2">
                <div className="w-6 h-6 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                <p>Rendering PDF pages...</p>
              </div>
            }
            error={
              <div className="flex flex-col items-center justify-center h-80 text-red-400 text-sm">
                <p>Failed to load PDF document.</p>
              </div>
            }
          >
            {numPages &&
              Array.from({ length: numPages }, (_, index) => {
                const pageNumber = index + 1;
                const dims = pageDimensions[pageNumber] || {
                  width: 612.0,
                  height: 792.0,
                };
                const origWidth = dims.width;
                const origHeight = dims.height;

                // Find clauses on this page
                const pageClauses = clauses.filter(
                  (c) => (c.page || 1) === pageNumber
                );

                return (
                  <div
                    key={pageNumber}
                    className="relative mb-6 shadow-2xl rounded-md overflow-hidden border border-zinc-800 bg-white"
                    style={{ width: targetWidth }}
                  >
                    <Page
                      pageNumber={pageNumber}
                      width={targetWidth}
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                      onLoadSuccess={(p) =>
                        handlePageLoadSuccess(pageNumber, {
                          originalWidth: p.originalWidth,
                          originalHeight: p.originalHeight,
                        })
                      }
                    />

                    {/* Overlay Highlights Layer */}
                    <div className="absolute inset-0 pointer-events-none">
                      {pageClauses.map((clause) => {
                        const isSelected = selectedClauseId === clause.id;
                        if (!clause.bboxes || clause.bboxes.length === 0)
                          return null;

                        // Calculate overall bounding box for anchor scrolling
                        const minY = Math.min(
                          ...clause.bboxes.map((b) => b[1])
                        );

                        return (
                          <React.Fragment key={clause.id}>
                            {/* Scroll Anchor positioned at top of clause */}
                            <div
                              id={`clause-${clause.id}`}
                              className="absolute left-0 w-full h-1 pointer-events-none -mt-4"
                              style={{
                                top: `${(minY / origHeight) * 100}%`,
                              }}
                            />

                            {/* Render highlight boxes for each span in this clause */}
                            {clause.bboxes.map((bbox, bIdx) => {
                              const [x0, y0, x1, y1] = bbox;
                              const leftPct = (x0 / origWidth) * 100;
                              const topPct = (y0 / origHeight) * 100;
                              const widthPct =
                                ((x1 - x0) / origWidth) * 100;
                              const heightPct =
                                ((y1 - y0) / origHeight) * 100;

                              return (
                                <div
                                  key={bIdx}
                                  onClick={() =>
                                    onSelectClause?.(clause.id)
                                  }
                                  className={`absolute transition-all duration-300 rounded ${
                                    isSelected
                                      ? "bg-amber-400/35 border-2 border-amber-500 shadow-[0_0_15px_rgba(245,158,11,0.6)] ring-2 ring-amber-300/40 z-30 pointer-events-auto cursor-pointer"
                                      : "bg-amber-400/10 border border-amber-400/25 z-10 hover:bg-amber-400/20 pointer-events-auto cursor-pointer"
                                  }`}
                                  style={{
                                    left: `${leftPct}%`,
                                    top: `${topPct}%`,
                                    width: `${widthPct}%`,
                                    height: `${heightPct}%`,
                                  }}
                                  title={`Clause ${clause.id}: ${
                                    clause.heading || clause.label || ""
                                  }`}
                                />
                              );
                            })}

                            {/* Floating Active Badge Tag */}
                            {isSelected && (
                              <div
                                className="absolute right-2 px-2 py-0.5 bg-amber-500 text-zinc-950 text-[10px] font-bold rounded shadow-lg z-40 pointer-events-none flex items-center gap-1"
                                style={{
                                  top: `${Math.max(
                                    1,
                                    (minY / origHeight) * 100 - 2
                                  )}%`,
                                }}
                              >
                                <CheckCircle2 className="w-3 h-3" />
                                <span>{clause.id}</span>
                              </div>
                            )}
                          </React.Fragment>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
          </Document>
        )}
      </div>
    </div>
  );
}
