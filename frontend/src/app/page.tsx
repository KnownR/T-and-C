"use client";

import React, { useState, useEffect, useRef } from "react";
import dynamic from "next/dynamic";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  AlertCircle,
  Info,
  Upload,
  FileText,
  FileUp,
  RotateCcw,
  CheckCircle2,
  Clock,
  Sparkles,
  Zap,
  ArrowRight,
  ServerCrash,
  FileX,
  Terminal,
  RefreshCw,
  Copy,
  Check,
  FileCheck2,
  Lock,
  Layers,
} from "lucide-react";
import {
  DocumentResponse,
  FindingModel,
  AnalysisResponse,
} from "@/types";
import TextViewer from "@/components/TextViewer";

// Dynamically import PdfViewer to disable server-side rendering (canvas/pdf.js requires browser window)
const PdfViewer = dynamic(() => import("@/components/PdfViewer"), {
  ssr: false,
  loading: () => (
    <div className="flex flex-col items-center justify-center h-full min-h-[450px] bg-zinc-950 border border-zinc-800 rounded-xl text-zinc-400 gap-3">
      <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-xs font-medium">Initializing PDF Rendering Engine...</p>
    </div>
  ),
});

const SAMPLE_TOS_TEXT = `CloudScale Terms of Service

1. Acceptance of Terms
By accessing or using the CloudScale Services, you agree to be bound by these Terms of Service. If you do not agree to these terms, do not use the Services.

2. Service Description
CloudScale provides managed cloud computing infrastructure, database hosting, and related developer tools as described on our website.

3. Modification of Terms
CloudScale reserves the right to modify, amend, or replace these Terms at any time at its sole discretion without prior notice to you. Your continued use of the Services following any changes constitutes acceptance of the modified Terms.

4. Limitation of Liability
To the maximum extent permitted by applicable law, in no event shall CloudScale, its affiliates, or directors be liable for any indirect, incidental, punitive, or consequential damages. In no event shall CloudScale's total aggregate liability exceed twenty-five dollars ($25.00).

5. Mandatory Binding Arbitration and Class Action Waiver
Any dispute, controversy, or claim arising out of or relating to this agreement shall be settled exclusively by confidential binding arbitration in Wilmington, Delaware. You hereby waive any right to participate as a plaintiff or class member in any class action or representative proceeding.

6. Termination of Services
CloudScale may suspend or terminate your access to the Services immediately, with or without cause, and without prior notice or liability. Upon termination, your right to use the Services will cease immediately.`;

const CLEAN_TOS_TEXT = `FriendlyCloud Mutual Terms of Service

1. Mutual Agreement and Duration
This Agreement takes effect upon mutual signature or account activation and continues on a month-to-month basis until terminated by either party with thirty (30) days advance written notice.

2. Service Commitments and Data Ownership
Customer retains all right, title, and ownership in and to Customer Data. FriendlyCloud processes Customer Data solely to provide the contracted Services in strict accordance with documented instructions and applicable privacy laws.

3. Bilateral Dispute Resolution
In the event of any dispute or controversy arising under this Agreement, the parties agree to first seek informal executive negotiation in good faith for thirty (30) days. Any subsequent judicial proceedings shall be conducted before courts of competent general jurisdiction with full preservation of all constitutional and statutory rights.

4. Mutual Termination for Cause
Either party may terminate this agreement upon thirty (30) days prior written notice if the other party materially breaches any provision and fails to cure such breach within the notice period.`;

const CATEGORY_LABELS: Record<string, string> = {
  arbitration: "Mandatory Arbitration",
  unilateral_change: "Unilateral Modification",
  limitation_of_liability: "Limitation of Liability",
  unilateral_termination: "Unilateral Termination",
  content_removal: "Content Removal",
  jurisdiction: "Forum Selection",
  choice_of_law: "Choice of Law",
  contract_by_using: "Contract by Mere Use",
};

interface ErrorDetails {
  status?: number;
  title: string;
  message: string;
  suggestion?: string;
  command?: string;
  canRetry?: boolean;
  canDryRun?: boolean;
}

export default function HomePage() {
  const [tab, setTab] = useState<"upload" | "paste">("upload");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [pastedText, setPastedText] = useState<string>("");
  const [isDragOver, setIsDragOver] = useState(false);

  // Analysis settings
  const [isDryRun, setIsDryRun] = useState(true);

  // State machine: idle -> uploading -> analyzing -> done | error
  const [status, setStatus] = useState<
    "idle" | "uploading" | "analyzing" | "done" | "error"
  >("idle");
  const [errorDetails, setErrorDetails] = useState<ErrorDetails | null>(null);
  const [progressMsg, setProgressMsg] = useState<string>("");
  const [elapsedSeconds, setElapsedSeconds] = useState<number>(0);
  const [copiedCommand, setCopiedCommand] = useState(false);

  // Data
  const [document, setDocument] = useState<DocumentResponse | null>(null);
  const [analysisResult, setAnalysisResult] = useState<AnalysisResponse | null>(
    null
  );
  const [filterSeverity, setFilterSeverity] = useState<string>("all");
  const [backendAlive, setBackendAlive] = useState<boolean | null>(null);

  // Active / Selected Citation state (one code path for click-to-scroll)
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [selectedClauseId, setSelectedClauseId] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // Check backend health on mount
  useEffect(() => {
    fetch("/api/health")
      .then((res) => {
        if (res.ok) setBackendAlive(true);
        else setBackendAlive(false);
      })
      .catch(() => setBackendAlive(false));
  }, []);

  // Timer while analyzing
  useEffect(() => {
    let interval: NodeJS.Timeout | null = null;
    if (status === "analyzing" || status === "uploading") {
      interval = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    } else {
      setElapsedSeconds(0);
    }
    return () => {
      if (interval) clearInterval(interval);
    };
  }, [status]);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const file = e.dataTransfer.files[0];
      setSelectedFile(file);
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
    }
  };

  // Sample Loaders for Pre-upload Landing
  const handleLoadSamplePdf = async () => {
    try {
      setErrorDetails(null);
      setTab("upload");
      const res = await fetch("/cloud_service_tos.pdf");
      if (!res.ok) throw new Error("Could not load sample PDF");
      const blob = await res.blob();
      const file = new File([blob], "cloud_service_tos.pdf", {
        type: "application/pdf",
      });
      setSelectedFile(file);
    } catch {
      setErrorDetails({
        status: 404,
        title: "Sample PDF Not Available",
        message: "Could not load /cloud_service_tos.pdf.",
      });
    }
  };

  const handleLoadSampleText = () => {
    setErrorDetails(null);
    setTab("paste");
    setPastedText(SAMPLE_TOS_TEXT);
  };

  const handleLoadCleanSample = () => {
    setErrorDetails(null);
    setTab("paste");
    setPastedText(CLEAN_TOS_TEXT);
  };

  // Unified scroll-to-clause for both PDF and Text renderers
  const handleSelectFinding = (finding: FindingModel) => {
    setSelectedFindingId(finding.id);
    setSelectedClauseId(finding.clause_id);

    // Scroll to the target clause element in whichever viewer is rendered
    setTimeout(() => {
      const el = window.document.getElementById(`clause-${finding.clause_id}`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 70);
  };

  const handleClauseClick = (clauseId: string) => {
    setSelectedClauseId(clauseId);
    const relatedFinding = analysisResult?.findings.find(
      (f) => f.clause_id === clauseId
    );
    if (relatedFinding) {
      setSelectedFindingId(relatedFinding.id);
    }
  };

  // Main flow: Ingest -> Poll Document Status -> Run Analysis -> Render Findings
  const handleAnalyze = async (overrideDryRun?: boolean) => {
    const dryRunMode = overrideDryRun !== undefined ? overrideDryRun : isDryRun;
    if (overrideDryRun !== undefined) {
      setIsDryRun(overrideDryRun);
    }

    setErrorDetails(null);
    setStatus("uploading");
    setProgressMsg("Ingesting document and segmenting clauses...");

    try {
      let createdDoc: DocumentResponse;

      if (tab === "upload") {
        if (!selectedFile) {
          throw {
            status: 400,
            title: "No File Selected",
            message: "Please choose or drag a PDF or text file to analyze.",
          };
        }

        const formData = new FormData();
        formData.append("file", selectedFile);
        const res = await fetch("/api/documents", {
          method: "POST",
          body: formData,
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          const detail = errData.detail || `Upload failed with HTTP ${res.status}`;

          if (res.status === 413) {
            throw {
              status: 413,
              title: "File Exceeds Size Cap (413)",
              message: detail,
              suggestion: "Please upload a smaller document under 10MB.",
            };
          } else if (res.status === 422) {
            throw {
              status: 422,
              title: "Unsupported File Format (422)",
              message: detail,
              suggestion:
                "Please upload a PDF (.pdf) or Plain Text (.txt) file.",
            };
          } else {
            throw {
              status: res.status,
              title: `Document Upload Error (${res.status})`,
              message: detail,
            };
          }
        }
        createdDoc = await res.json();
      } else {
        if (!pastedText.trim()) {
          throw {
            status: 400,
            title: "Empty Contract Text",
            message: "Please enter or paste contract terms to analyze.",
          };
        }
        const res = await fetch("/api/documents", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: pastedText,
            filename: "pasted_terms.txt",
          }),
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          throw {
            status: res.status,
            title: `Document Ingestion Error (${res.status})`,
            message:
              errData.detail || `Ingestion failed with HTTP ${res.status}`,
          };
        }
        createdDoc = await res.json();
      }

      setDocument(createdDoc);
      setStatus("analyzing");
      setProgressMsg(
        dryRunMode
          ? "Running deterministic UNFAIR-ToS rubric verification ($0 offline mode)..."
          : "Analyzing clauses with local Ollama LLM (qwen2.5:7b-instruct)..."
      );

      // Start polling document status in background
      const docId = createdDoc.id;
      const pollInterval = setInterval(async () => {
        try {
          const pollRes = await fetch(`/api/documents/${docId}`);
          if (pollRes.ok) {
            const polledData: DocumentResponse = await pollRes.json();
            setDocument(polledData);
            if (polledData.status === "analyzed") {
              setProgressMsg("Analysis complete. Loading verified findings...");
            }
          }
        } catch {
          // ignore transient poll error
        }
      }, 1000);

      // Trigger analysis endpoint
      const analyzeUrl = `/api/documents/${docId}/analyze?lens=tos&dry_run=${dryRunMode}`;
      const analyzeRes = await fetch(analyzeUrl, {
        method: "POST",
      });

      clearInterval(pollInterval);

      if (!analyzeRes.ok) {
        const errJson = await analyzeRes.json().catch(() => ({}));
        const detail = errJson.detail || `Analysis failed with HTTP ${analyzeRes.status}`;
        const isOllamaDown =
          analyzeRes.status === 502 ||
          detail.toLowerCase().includes("ollama not reachable") ||
          detail.toLowerCase().includes("actively refused") ||
          detail.toLowerCase().includes("connection");

        if (isOllamaDown) {
          throw {
            status: 502,
            title: "Ollama LLM Unreachable (502)",
            message: detail,
            command: "ollama serve",
            suggestion:
              "Run 'ollama serve' in your terminal and ensure model 'qwen2.5:7b-instruct' is pulled ('ollama pull qwen2.5:7b-instruct'). Alternatively, switch to Fast Dry-Run mode.",
            canRetry: true,
            canDryRun: true,
          };
        } else if (analyzeRes.status === 404) {
          throw {
            status: 404,
            title: "Document Not Found (404)",
            message: detail,
            suggestion: "The document may have expired or been removed from the database.",
          };
        } else {
          // 500 / LLM validation failure
          throw {
            status: analyzeRes.status,
            title: `LLM Analysis Failed (${analyzeRes.status})`,
            message: detail,
            suggestion:
              "The model output failed schema validation after retries. You can try again or run in deterministic Fast Dry-Run mode.",
            canRetry: true,
            canDryRun: true,
          };
        }
      }

      const result: AnalysisResponse = await analyzeRes.json();
      setAnalysisResult(result);

      // Re-fetch document one final time
      const finalDocRes = await fetch(`/api/documents/${docId}`).catch(
        () => null
      );
      if (finalDocRes && finalDocRes.ok) {
        const finalDoc = await finalDocRes.json();
        setDocument(finalDoc);
      }

      setStatus("done");

      // Auto-select first finding if available
      if (result.findings.length > 0) {
        handleSelectFinding(result.findings[0]);
      }
    } catch (err: unknown) {
      setStatus("error");
      if (
        typeof err === "object" &&
        err !== null &&
        "title" in err &&
        "message" in err
      ) {
        setErrorDetails(err as ErrorDetails);
      } else {
        const msg =
          err instanceof Error ? err.message : "An unexpected error occurred.";
        setErrorDetails({
          status: 500,
          title: "Unexpected Error",
          message: msg,
          canRetry: true,
          canDryRun: true,
        });
      }
    }
  };

  const handleReset = () => {
    setStatus("idle");
    setSelectedFile(null);
    setPastedText("");
    setDocument(null);
    setAnalysisResult(null);
    setSelectedFindingId(null);
    setSelectedClauseId(null);
    setErrorDetails(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const copyCommandToClipboard = (cmd: string) => {
    navigator.clipboard.writeText(cmd);
    setCopiedCommand(true);
    setTimeout(() => setCopiedCommand(false), 2000);
  };

  const findings = analysisResult?.findings || [];
  const filteredFindings = findings.filter((f) => {
    if (filterSeverity === "all") return true;
    return f.severity === filterSeverity;
  });

  const redCount = findings.filter((f) => f.severity === "red").length;
  const yellowCount = findings.filter((f) => f.severity === "yellow").length;

  // Grounding statistics derived directly from findings payload
  const verifiedCount = findings.filter(
    (f) => f.verification_status === "verified"
  ).length;
  const fuzzyCount = findings.filter(
    (f) => f.verification_status === "verified_fuzzy"
  ).length;
  const reanchoredCount = findings.filter(
    (f) => f.verification_status === "reanchored"
  ).length;

  const selectedFinding =
    findings.find((f) => f.id === selectedFindingId) || null;

  return (
    <div className="flex flex-col min-h-screen bg-slate-950 text-slate-100 font-sans antialiased">
      {/* Top Header */}
      <header className="border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-md sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-violet-600 to-cyan-400 p-[1px] shadow-lg shadow-indigo-500/20">
              <div className="h-full w-full bg-slate-950 rounded-xl flex items-center justify-center">
                <ShieldCheck className="h-5 w-5 text-indigo-400" />
              </div>
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-lg tracking-tight bg-gradient-to-r from-white via-slate-200 to-slate-400 bg-clip-text text-transparent">
                  What Did I Agree To?
                </span>
                <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
                  Phase 6b
                </span>
              </div>
              <p className="text-xs text-slate-400 hidden sm:block">
                Local-first legal Terms of Service analyzer with verified citations
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-3">
            {backendAlive === true ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Backend Connected
              </span>
            ) : backendAlive === false ? (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
                <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                Backend Offline
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium bg-slate-800 text-slate-400">
                Checking connection...
              </span>
            )}
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* HERO BANNER & INTRO (visible on idle / error) */}
        {(status === "idle" || status === "error") && (
          <div className="text-center mb-8 pt-2 sm:pt-4">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-slate-800/80 border border-slate-700/60 text-xs text-slate-300 mb-4 shadow-inner">
              <Sparkles className="h-3.5 w-3.5 text-indigo-400" />
              <span>Deterministic Citation Verification — No Fabricated Claims</span>
            </div>
            <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-white mb-3">
              Know what you sign before you click{" "}
              <span className="bg-gradient-to-r from-indigo-400 via-violet-400 to-cyan-400 bg-clip-text text-transparent">
                &ldquo;I Agree&rdquo;
              </span>
            </h1>
            <p className="text-slate-400 max-w-2xl mx-auto text-sm sm:text-base leading-relaxed">
              Upload any contract or Terms of Service PDF. Our local AI pipeline segments clauses,
              detects unfair provisions like arbitration traps and unilateral waivers, and
              verifies every quote character-for-character against the original text.
            </p>
          </div>
        )}

        {/* ERROR SURFACING CARD (readable, styled error state) */}
        {status === "error" && errorDetails && (
          <div className="mb-8 p-6 rounded-2xl bg-rose-950/20 border border-rose-500/30 text-rose-200 shadow-xl backdrop-blur-sm animate-in fade-in duration-200">
            <div className="flex flex-col sm:flex-row items-start justify-between gap-4">
              <div className="flex items-start gap-3.5">
                <div className="w-10 h-10 rounded-xl bg-rose-500/15 border border-rose-500/30 flex items-center justify-center text-rose-400 shrink-0">
                  {errorDetails.status === 502 ? (
                    <ServerCrash className="h-5 w-5" />
                  ) : errorDetails.status === 413 || errorDetails.status === 422 ? (
                    <FileX className="h-5 w-5" />
                  ) : (
                    <AlertCircle className="h-5 w-5" />
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-bold text-white text-base">
                      {errorDetails.title}
                    </h3>
                    {errorDetails.status && (
                      <span className="px-2 py-0.5 text-[11px] font-mono font-bold bg-rose-500/20 border border-rose-500/30 text-rose-300 rounded">
                        HTTP {errorDetails.status}
                      </span>
                    )}
                  </div>
                  <p className="mt-1.5 text-xs sm:text-sm text-rose-200/90 leading-relaxed">
                    {errorDetails.message}
                  </p>
                  {errorDetails.suggestion && (
                    <p className="mt-2 text-xs text-rose-300/80 font-medium">
                      💡 {errorDetails.suggestion}
                    </p>
                  )}

                  {/* Suggestion command block */}
                  {errorDetails.command && (
                    <div className="mt-3 flex items-center gap-2 bg-slate-950/80 border border-slate-800 rounded-lg p-2.5 max-w-md">
                      <Terminal className="w-4 h-4 text-emerald-400 shrink-0" />
                      <code className="text-xs font-mono text-emerald-300 flex-1">
                        {errorDetails.command}
                      </code>
                      <button
                        type="button"
                        onClick={() =>
                          copyCommandToClipboard(errorDetails.command!)
                        }
                        className="p-1 hover:bg-slate-800 text-slate-400 hover:text-white rounded transition"
                        title="Copy command"
                      >
                        {copiedCommand ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2 self-end sm:self-start shrink-0">
                {errorDetails.canRetry && (
                  <button
                    type="button"
                    onClick={() => handleAnalyze()}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-semibold shadow-md transition cursor-pointer"
                  >
                    <RefreshCw className="w-3.5 h-3.5" />
                    Try Again
                  </button>
                )}
                {errorDetails.canDryRun && (
                  <button
                    type="button"
                    onClick={() => handleAnalyze(true)}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium border border-slate-700 transition cursor-pointer"
                  >
                    <Zap className="w-3.5 h-3.5 text-amber-400" />
                    Use Fast Dry-Run
                  </button>
                )}
                <button
                  type="button"
                  onClick={handleReset}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-slate-400 hover:text-white text-xs font-medium border border-slate-800 transition cursor-pointer"
                >
                  Clear
                </button>
              </div>
            </div>
          </div>
        )}

        {/* INPUT STATE (Idle or Error with form) */}
        {(status === "idle" || status === "error") && (
          <div className="space-y-8">
            <div className="bg-slate-900/50 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl backdrop-blur-sm">
              {/* Tab Navigation */}
              <div className="flex border-b border-slate-800 mb-6 gap-2">
                <button
                  type="button"
                  onClick={() => setTab("upload")}
                  className={`flex items-center gap-2 pb-3 px-4 text-sm font-medium border-b-2 transition-all cursor-pointer ${
                    tab === "upload"
                      ? "border-indigo-500 text-indigo-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <Upload className="h-4 w-4" />
                  Upload PDF / TXT
                </button>
                <button
                  type="button"
                  onClick={() => setTab("paste")}
                  className={`flex items-center gap-2 pb-3 px-4 text-sm font-medium border-b-2 transition-all cursor-pointer ${
                    tab === "paste"
                      ? "border-indigo-500 text-indigo-400"
                      : "border-transparent text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <FileText className="h-4 w-4" />
                  Paste Text
                </button>
              </div>

              {/* TAB 1: FILE DROPZONE */}
              {tab === "upload" && (
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDragOver(true);
                  }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-xl p-8 sm:p-12 text-center cursor-pointer transition-all ${
                    isDragOver
                      ? "border-indigo-500 bg-indigo-500/10 scale-[0.99]"
                      : "border-slate-700/80 hover:border-slate-600 bg-slate-950/40 hover:bg-slate-900/40"
                  }`}
                >
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileChange}
                    accept=".pdf,.txt"
                    className="hidden"
                  />

                  <div className="mx-auto w-14 h-14 rounded-2xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-4 shadow-inner">
                    <FileUp className="h-7 w-7" />
                  </div>

                  {selectedFile ? (
                    <div className="space-y-1">
                      <p className="font-semibold text-white text-base">
                        {selectedFile.name}
                      </p>
                      <p className="text-xs text-slate-400">
                        {(selectedFile.size / 1024).toFixed(1)} KB • Click to choose a different file
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <p className="text-sm font-semibold text-white">
                        Drop contract PDF or text file here, or{" "}
                        <span className="text-indigo-400 underline underline-offset-2">
                          browse files
                        </span>
                      </p>
                      <p className="text-xs text-slate-400">
                        Supports PDF (.pdf) and plain text (.txt) up to 10MB. Runs 100% locally.
                      </p>
                    </div>
                  )}
                </div>
              )}

              {/* TAB 2: PASTE TEXT AREA */}
              {tab === "paste" && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between text-xs text-slate-400">
                    <span>Paste legal terms, policies, or agreements below:</span>
                    <button
                      type="button"
                      onClick={handleLoadSampleText}
                      className="text-indigo-400 hover:text-indigo-300 font-medium cursor-pointer transition-colors"
                    >
                      Load Sample Document
                    </button>
                  </div>
                  <textarea
                    value={pastedText}
                    onChange={(e) => setPastedText(e.target.value)}
                    placeholder="Paste contract terms or clause text here..."
                    rows={9}
                    className="w-full bg-slate-950/60 border border-slate-800 rounded-xl p-4 text-xs sm:text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent font-mono leading-relaxed"
                  />
                </div>
              )}

              {/* Pre-upload Landing: Sample Documents Bar */}
              <div className="mt-4 flex items-center gap-2 flex-wrap text-xs text-slate-400">
                <span className="font-medium text-slate-500">Quick Samples:</span>
                <button
                  type="button"
                  onClick={handleLoadSamplePdf}
                  className="px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-800 text-slate-300 border border-slate-700/60 transition cursor-pointer"
                >
                  📄 CloudScale ToS (PDF)
                </button>
                <button
                  type="button"
                  onClick={handleLoadSampleText}
                  className="px-2.5 py-1 rounded-lg bg-slate-800/80 hover:bg-slate-800 text-slate-300 border border-slate-700/60 transition cursor-pointer"
                >
                  📝 CloudScale ToS (Text)
                </button>
                <button
                  type="button"
                  onClick={handleLoadCleanSample}
                  className="px-2.5 py-1 rounded-lg bg-emerald-950/40 hover:bg-emerald-900/40 text-emerald-300 border border-emerald-800/40 transition cursor-pointer"
                >
                  🛡️ FriendlyCloud Agreement (Clean 0-Findings)
                </button>
              </div>

              {/* Engine Options & Submit Action */}
              <div className="mt-6 pt-6 border-t border-slate-800 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <label className="text-xs font-medium text-slate-400 flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isDryRun}
                      onChange={(e) => setIsDryRun(e.target.checked)}
                      className="rounded border-slate-700 bg-slate-950 text-indigo-600 focus:ring-indigo-500 h-4 w-4"
                    />
                    <span>
                      Fast Dry-Run Mode{" "}
                      <span className="text-slate-500">($0 / ~30ms offline)</span>
                    </span>
                  </label>
                </div>

                <button
                  type="button"
                  onClick={() => handleAnalyze()}
                  disabled={tab === "upload" ? !selectedFile : !pastedText.trim()}
                  className="inline-flex items-center justify-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-semibold shadow-lg shadow-indigo-600/30 transition-all cursor-pointer"
                >
                  <Zap className="h-4 w-4" />
                  Analyze Terms of Service
                </button>
              </div>
            </div>

            {/* PRE-UPLOAD LANDING: Feature Highlights (What the tool does) */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800/80">
                <div className="w-8 h-8 rounded-lg bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400 mb-2.5">
                  <Layers className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-white mb-1">
                  Clause Segmentation
                </h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Extracts raw bounding boxes &amp; isolates numbered legal clauses deterministically.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800/80">
                <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 mb-2.5">
                  <ShieldAlert className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-white mb-1">
                  UNFAIR-ToS Rubric
                </h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Screens 8 consumer-risk dimensions including arbitration traps and unilateral waivers.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800/80">
                <div className="w-8 h-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-2.5">
                  <FileCheck2 className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-white mb-1">
                  Deterministic Grounding
                </h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Every proposed quote is verified character-for-character before showing. No hallucinations.
                </p>
              </div>

              <div className="p-4 rounded-xl bg-slate-900/30 border border-slate-800/80">
                <div className="w-8 h-8 rounded-lg bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400 mb-2.5">
                  <Lock className="w-4 h-4" />
                </div>
                <h4 className="text-xs font-bold text-white mb-1">
                  100% Local Privacy
                </h4>
                <p className="text-[11px] text-slate-400 leading-relaxed">
                  Runs on your machine with Ollama and SQLite. Zero cloud leaks, zero API costs.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* LOADING SKELETONS: Full Mockup Replacing Bare Spinner */}
        {(status === "uploading" || status === "analyzing") && (
          <div className="space-y-6">
            {/* Top Shimmer Progress Bar */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 backdrop-blur-sm shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded-xl bg-indigo-500/15 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shrink-0">
                    <Zap className="w-4 h-4 animate-bounce" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-white">
                      Analyzing Legal Document…
                    </h3>
                    <p className="text-xs text-slate-400 mt-0.5">{progressMsg}</p>
                  </div>
                </div>

                <div className="inline-flex items-center gap-3 px-3.5 py-1.5 rounded-full bg-slate-950/80 border border-slate-800 text-xs text-slate-400 self-start sm:self-auto">
                  <span className="flex items-center gap-1.5">
                    <Clock className="h-3.5 w-3.5 text-indigo-400" />
                    Elapsed:{" "}
                    <strong className="text-white">{elapsedSeconds}s</strong>
                  </span>
                  <span className="text-slate-700">•</span>
                  <span>
                    Status:{" "}
                    <strong className="text-indigo-300 uppercase">
                      {document?.status || "uploading"}
                    </strong>
                  </span>
                  {document && (
                    <>
                      <span className="text-slate-700">•</span>
                      <span>
                        Clauses:{" "}
                        <strong className="text-white">
                          {document.clauses?.length ?? "..."}
                        </strong>
                      </span>
                    </>
                  )}
                </div>
              </div>

              {/* Shimmer line */}
              <div className="mt-4 h-1.5 w-full bg-slate-800/80 rounded-full overflow-hidden">
                <div className="h-full bg-gradient-to-r from-indigo-500 via-violet-500 to-cyan-400 rounded-full animate-pulse w-3/4" />
              </div>
            </div>

            {/* Split Screen Skeletons */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* LEFT PANE: Document Viewer Skeleton */}
              <div className="lg:col-span-7 h-[560px] lg:h-[580px] bg-zinc-950 border border-zinc-800 rounded-xl p-4 flex flex-col overflow-hidden shadow-2xl">
                {/* Header Toolbar Skeleton */}
                <div className="w-full h-8 bg-zinc-900 border-b border-zinc-800 rounded-t-lg mb-4 flex items-center justify-between px-3 animate-pulse">
                  <div className="h-3.5 w-36 bg-zinc-800 rounded" />
                  <div className="h-4 w-28 bg-zinc-800 rounded" />
                </div>

                {/* Document Canvas Skeleton */}
                <div className="flex-1 bg-zinc-900/30 rounded-lg p-6 flex flex-col items-center justify-start space-y-4 overflow-hidden custom-scrollbar animate-pulse">
                  <div className="w-full max-w-[540px] bg-white/[0.03] border border-zinc-800/60 rounded-lg p-8 space-y-4">
                    <div className="h-4 w-1/2 bg-zinc-800/80 rounded" />
                    <div className="h-2.5 w-full bg-zinc-800/50 rounded" />
                    <div className="h-2.5 w-11/12 bg-zinc-800/50 rounded" />
                    <div className="h-2.5 w-4/5 bg-zinc-800/50 rounded" />

                    <div className="pt-4 border-t border-zinc-800/40 space-y-3">
                      <div className="h-3.5 w-1/3 bg-zinc-800/80 rounded" />
                      <div className="h-2.5 w-full bg-zinc-800/50 rounded" />
                      <div className="h-2.5 w-5/6 bg-zinc-800/50 rounded" />
                    </div>

                    <div className="pt-4 border-t border-zinc-800/40 space-y-3">
                      <div className="h-3.5 w-2/5 bg-zinc-800/80 rounded" />
                      <div className="h-2.5 w-full bg-zinc-800/50 rounded" />
                      <div className="h-2.5 w-3/4 bg-zinc-800/50 rounded" />
                    </div>
                  </div>
                </div>
              </div>

              {/* RIGHT PANE: Findings List Skeleton */}
              <div className="lg:col-span-5 h-[560px] lg:h-[580px] bg-slate-900/40 border border-slate-800/80 rounded-2xl p-4 flex flex-col space-y-3 overflow-hidden shadow-xl">
                {/* Header Skeleton */}
                <div className="pb-3 border-b border-slate-800 flex items-center justify-between animate-pulse">
                  <div className="h-4 w-40 bg-slate-800 rounded" />
                  <div className="h-3 w-24 bg-slate-800/60 rounded" />
                </div>

                {/* Cards Skeletons */}
                <div className="flex-1 space-y-3 overflow-y-auto pr-1 custom-scrollbar">
                  {[1, 2, 3].map((idx) => (
                    <div
                      key={idx}
                      className="p-4 rounded-xl border border-slate-800/80 bg-slate-900/50 space-y-3 animate-pulse"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <div className="h-5 w-16 bg-rose-500/10 rounded" />
                          <div className="h-5 w-24 bg-slate-800 rounded" />
                        </div>
                        <div className="h-4 w-12 bg-slate-800 rounded" />
                      </div>
                      <div className="h-3.5 w-2/3 bg-slate-700/60 rounded" />
                      <div className="space-y-1.5">
                        <div className="h-2.5 w-full bg-slate-800/60 rounded" />
                        <div className="h-2.5 w-4/5 bg-slate-800/60 rounded" />
                      </div>
                      <div className="h-10 w-full bg-slate-950/70 border border-slate-800/60 rounded-lg" />
                      <div className="flex items-center justify-between pt-2 border-t border-slate-800/40">
                        <div className="h-3 w-24 bg-emerald-500/15 rounded" />
                        <div className="h-3 w-16 bg-slate-800/60 rounded" />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* COMPLETED STATE: Split-Screen View (Document Viewer + Findings List) */}
        {status === "done" && analysisResult && document && (
          <div className="space-y-6">
            {/* Top Document Header & Grounding Telemetry Banner */}
            <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-5 sm:p-6 backdrop-blur-sm shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-slate-800">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-xl font-bold text-white">
                      Legal Risk Analysis Report
                    </h2>
                    <span className="text-xs px-2.5 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                      Analysis Complete
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    Document:{" "}
                    <span className="text-slate-200 font-medium">
                      {document.filename || "Uploaded Contract"}
                    </span>{" "}
                    • {document.clauses.length} clauses segmented
                  </p>
                </div>

                <button
                  type="button"
                  onClick={handleReset}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium border border-slate-700 transition-colors w-fit cursor-pointer"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                  Analyze Another Document
                </button>
              </div>

              {/* Grounding Statistics Grid (derived from findings payload) */}
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-3 mt-4">
                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Grounding Rate
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-emerald-400">
                      {findings.length > 0
                        ? `${(analysisResult.run.grounding_rate * 100).toFixed(0)}%`
                        : "100%"}
                    </span>
                    <span className="text-[10px] text-slate-400">overall</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Exact Verified
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-emerald-300">
                      {verifiedCount}
                    </span>
                    <span className="text-[10px] text-slate-400">findings</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Fuzzy Verified
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-amber-300">
                      {fuzzyCount}
                    </span>
                    <span className="text-[10px] text-slate-400">near-miss</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Reanchored
                  </span>
                  <div className="flex items-baseline gap-1 mt-1">
                    <span className="text-xl font-extrabold text-sky-300">
                      {reanchoredCount}
                    </span>
                    <span className="text-[10px] text-slate-400">relocated</span>
                  </div>
                </div>

                <div className="bg-slate-950/70 p-3 rounded-xl border border-slate-800/80 col-span-2 sm:col-span-1">
                  <span className="text-[10px] font-medium text-slate-400 uppercase tracking-wider block">
                    Latency & Cost
                  </span>
                  <div className="mt-1">
                    <span className="text-sm font-bold text-white block">
                      {analysisResult.run.latency_ms > 1000
                        ? `${(analysisResult.run.latency_ms / 1000).toFixed(1)}s`
                        : `${analysisResult.run.latency_ms.toFixed(0)}ms`}
                    </span>
                    <span className="text-[10px] text-slate-400">
                      ${analysisResult.run.cost_usd.toFixed(4)}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            {/* SPLIT SCREEN VIEW: Document Viewer Beside Findings List */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* LEFT PANE: Document Viewer (PDF or Text) */}
              <div className="lg:col-span-7 h-[560px] lg:h-[580px] flex flex-col">
                {document.source_type === "pdf" ? (
                  <PdfViewer
                    file={selectedFile}
                    clauses={document.clauses}
                    selectedClauseId={selectedClauseId}
                    onSelectClause={handleClauseClick}
                  />
                ) : (
                  <TextViewer
                    clauses={document.clauses}
                    selectedClauseId={selectedClauseId}
                    onSelectClause={handleClauseClick}
                    selectedFindingQuote={selectedFinding?.quote}
                  />
                )}
              </div>

              {/* RIGHT PANE: Findings List OR Zero Findings Empty State */}
              <div className="lg:col-span-5 h-[560px] lg:h-[580px] flex flex-col bg-slate-900/40 border border-slate-800/80 rounded-2xl p-4 backdrop-blur-sm shadow-xl">
                {findings.length === 0 ? (
                  /* ZERO FINDINGS DETECTED EMPTY STATE */
                  <div className="flex-1 flex flex-col items-center justify-center p-6 text-center space-y-4">
                    <div className="w-16 h-16 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shadow-lg shadow-emerald-500/10">
                      <ShieldCheck className="w-8 h-8" />
                    </div>

                    <div className="space-y-1.5 max-w-sm">
                      <h3 className="text-base font-bold text-white">
                        No Red Flags Detected
                      </h3>
                      <p className="text-xs text-slate-300 leading-relaxed">
                        None of the {document.clauses.length} segmented clauses matched the 8 UNFAIR-ToS risk categories.
                      </p>
                    </div>

                    {/* Prominent Legal Caveat */}
                    <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800 text-left text-[11px] text-slate-400 space-y-1 leading-relaxed">
                      <div className="flex items-center gap-1.5 text-amber-300 font-semibold">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                        <span>Absence of red flags is not a guarantee</span>
                      </div>
                      <p>
                        The absence of detected unfair terms is not a legal guarantee of compliance, safety, or mutual benefit. Standard boilerplate provisions may still impose significant obligations. Always consult qualified legal counsel for binding agreements.
                      </p>
                    </div>

                    <div className="text-[11px] text-slate-500">
                      You can review all segmented clauses in the document viewer on the left.
                    </div>
                  </div>
                ) : (
                  /* FINDINGS LIST */
                  <>
                    {/* Findings Header & Filter */}
                    <div className="pb-3 border-b border-slate-800 flex flex-col gap-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-slate-200 uppercase tracking-wider flex items-center gap-1.5">
                          <ShieldAlert className="w-4 h-4 text-amber-400" />
                          Detected Unfair Terms ({findings.length})
                        </span>
                        <span className="text-[11px] text-slate-400">
                          Click a finding to highlight
                        </span>
                      </div>

                      {/* Filter Pills */}
                      <div className="flex items-center gap-1 bg-slate-950/80 border border-slate-800/80 p-1 rounded-xl text-xs">
                        <button
                          type="button"
                          onClick={() => setFilterSeverity("all")}
                          className={`flex-1 py-1 px-2 rounded-lg font-medium text-center transition-all cursor-pointer ${
                            filterSeverity === "all"
                              ? "bg-slate-800 text-white"
                              : "text-slate-400 hover:text-slate-200"
                          }`}
                        >
                          All ({findings.length})
                        </button>
                        <button
                          type="button"
                          onClick={() => setFilterSeverity("red")}
                          className={`flex-1 py-1 px-2 rounded-lg font-medium text-center transition-all flex items-center justify-center gap-1 cursor-pointer ${
                            filterSeverity === "red"
                              ? "bg-rose-500/20 text-rose-300 border border-rose-500/30"
                              : "text-slate-400 hover:text-rose-300"
                          }`}
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
                          Red ({redCount})
                        </button>
                        <button
                          type="button"
                          onClick={() => setFilterSeverity("yellow")}
                          className={`flex-1 py-1 px-2 rounded-lg font-medium text-center transition-all flex items-center justify-center gap-1 cursor-pointer ${
                            filterSeverity === "yellow"
                              ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
                              : "text-slate-400 hover:text-amber-300"
                          }`}
                        >
                          <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
                          Yellow ({yellowCount})
                        </button>
                      </div>
                    </div>

                    {/* Findings Cards List */}
                    <div className="flex-1 overflow-y-auto space-y-3 pt-3 pr-1 custom-scrollbar">
                      {filteredFindings.length === 0 ? (
                        <div className="h-64 flex flex-col items-center justify-center text-center p-6 text-slate-400 text-xs">
                          <CheckCircle2 className="w-8 h-8 text-emerald-400 mb-2" />
                          <p>No findings for the selected filter.</p>
                        </div>
                      ) : (
                        filteredFindings.map((finding) => {
                          const isSelected = selectedFindingId === finding.id;

                          return (
                            <div
                              key={finding.id}
                              onClick={() => handleSelectFinding(finding)}
                              className={`p-4 rounded-xl border transition-all duration-200 cursor-pointer text-left ${
                                isSelected
                                  ? "bg-amber-950/20 border-amber-500 ring-2 ring-amber-400/50 shadow-xl shadow-amber-500/10 scale-[1.01]"
                                  : "bg-slate-900/60 border-slate-800/80 hover:border-slate-700 hover:bg-slate-900/90"
                              }`}
                            >
                              {/* Top Badges Row */}
                              <div className="flex items-center justify-between gap-2 mb-2">
                                <div className="flex items-center gap-2">
                                  {/* Severity Badge */}
                                  <span
                                    className={`text-[10px] font-bold px-2 py-0.5 rounded-md uppercase tracking-wider flex items-center gap-1 ${
                                      finding.severity === "red"
                                        ? "bg-rose-500/15 text-rose-300 border border-rose-500/30"
                                        : finding.severity === "yellow"
                                        ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                                        : "bg-sky-500/15 text-sky-300 border border-sky-500/30"
                                    }`}
                                  >
                                    {finding.severity === "red" && (
                                      <AlertCircle className="h-3 w-3" />
                                    )}
                                    {finding.severity === "yellow" && (
                                      <AlertTriangle className="h-3 w-3" />
                                    )}
                                    {finding.severity === "info" && (
                                      <Info className="h-3 w-3" />
                                    )}
                                    {finding.severity === "red"
                                      ? "High Risk"
                                      : finding.severity === "yellow"
                                      ? "Caution"
                                      : "Info"}
                                  </span>

                                  {/* Category Badge */}
                                  <span className="text-[11px] font-medium text-slate-300 bg-slate-800 px-2 py-0.5 rounded border border-slate-700/60">
                                    {CATEGORY_LABELS[finding.category] ||
                                      finding.category}
                                  </span>
                                </div>

                                {/* Clause Reference */}
                                <span
                                  className={`text-[10px] font-mono px-2 py-0.5 rounded font-bold ${
                                    isSelected
                                      ? "bg-amber-500 text-zinc-950"
                                      : "bg-slate-950 text-slate-400 border border-slate-800"
                                  }`}
                                >
                                  Clause {finding.clause_id}
                                </span>
                              </div>

                              {/* Title & Explanation */}
                              <h3 className="text-xs font-bold text-white mb-1">
                                {finding.title}
                              </h3>
                              <p className="text-xs text-slate-300 leading-relaxed mb-3">
                                {finding.explanation}
                              </p>

                              {/* Verbatim Quoted Text Box */}
                              <div className="bg-slate-950/80 border border-slate-800/80 rounded-lg p-2.5 text-[11px] font-mono text-slate-300 leading-normal mb-2.5">
                                <span className="text-amber-400 font-bold mr-1">“</span>
                                {finding.quote}
                                <span className="text-amber-400 font-bold ml-1">”</span>
                              </div>

                              {/* Bottom Verification & Click indicator */}
                              <div className="flex items-center justify-between pt-2 border-t border-slate-800/60 text-[10px]">
                                <span className="flex items-center gap-1 font-medium text-emerald-400">
                                  <CheckCircle2 className="w-3 h-3" />
                                  {finding.verification_status === "verified"
                                    ? "Exact Verified"
                                    : finding.verification_status === "verified_fuzzy"
                                    ? "Fuzzy Verified"
                                    : "Reanchored"}{" "}
                                  {finding.match_score ? `(${finding.match_score.toFixed(0)}%)` : ""}
                                </span>

                                {isSelected ? (
                                  <span className="text-amber-400 font-bold flex items-center gap-1">
                                    Viewing in Doc <ArrowRight className="w-3 h-3" />
                                  </span>
                                ) : (
                                  <span className="text-slate-500 flex items-center gap-0.5 group-hover:text-slate-300">
                                    Click to highlight
                                  </span>
                                )}
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </>
                )}
              </div>
            </div>
          </div>
        )}
      </main>

      {/* Mandatory Disclaimer Footer (Always Visible in Frame) */}
      <footer className="border-t border-slate-800/80 bg-slate-900/40 py-5 mt-auto">
        <div className="max-w-7xl mx-auto px-4 text-center">
          <p className="text-xs text-slate-400 font-medium">
            This tool explains documents. It is not legal advice.
          </p>
        </div>
      </footer>
    </div>
  );
}
