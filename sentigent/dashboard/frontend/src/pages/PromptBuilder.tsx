import { useState } from "react";
import {
  Sparkles, ArrowRight, RotateCcw, CheckCircle2, ChevronRight, Code2,
  FileText, Bug, RefreshCw, Globe, Layers, ListTodo,
} from "lucide-react";
import { usePromptTemplates } from "@/api/hooks";
import { api } from "@/api/client";
import { Card, CardHeader, CardTitle, CardBody, Badge } from "@/components/ui";
import type { TemplateInfo, TemplateName, PromptSession } from "@/types";

const TEMPLATE_ICONS: Record<TemplateName, React.ReactNode> = {
  product_spec: <FileText size={16} />,
  pr_review: <Code2 size={16} />,
  bug_report: <Bug size={16} />,
  code_refactor: <RefreshCw size={16} />,
  architecture_decision: <Layers size={16} />,
  api_design: <Globe size={16} />,
  task_breakdown: <ListTodo size={16} />,
};

const TEMPLATE_COLORS: Record<TemplateName, string> = {
  product_spec: "text-purple-400",
  pr_review: "text-blue-400",
  bug_report: "text-red-400",
  code_refactor: "text-yellow-400",
  architecture_decision: "text-green-400",
  api_design: "text-cyan-400",
  task_breakdown: "text-orange-400",
};

function TemplateCard({ template, onSelect }: { template: TemplateInfo; onSelect: () => void }) {
  const colorClass = TEMPLATE_COLORS[template.name as TemplateName] ?? "text-accent-light";
  const icon = TEMPLATE_ICONS[template.name as TemplateName];

  return (
    <button
      onClick={onSelect}
      className="group text-left p-5 rounded-xl bg-bg-surface border border-bg-border hover:border-accent/35 transition-all duration-200 flex flex-col gap-3 stat-card"
      style={{ background: "linear-gradient(135deg, #0d1117 0%, #111827 100%)" }}
    >
      <div className="flex items-start justify-between">
        <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${colorClass}`}
          style={{ background: "rgba(255,255,255,0.05)" }}>
          {icon}
        </div>
        <ChevronRight size={13} className="text-muted group-hover:text-accent-light transition-colors mt-1" />
      </div>
      <div>
        <div className="text-sm font-semibold text-white capitalize mb-1.5">
          {template.name.replace(/_/g, " ")}
        </div>
        <p className="text-[11px] text-muted leading-relaxed">{template.description}</p>
      </div>
      <div className="flex items-center gap-2 text-[10px] pt-1 border-t border-bg-border/50">
        <span className="text-muted/60">{template.required_fields} required · {template.fields} fields</span>
        <span className="ml-auto font-mono text-accent-light/60">{template.skill}</span>
      </div>
    </button>
  );
}

interface SessionUIProps {
  session: PromptSession;
  onAnswer: (ans: string) => void;
  onSkip: () => void;
  onAbandon: () => void;
  isLoading: boolean;
}

function SessionUI({ session, onAnswer, onSkip, onAbandon, isLoading }: SessionUIProps) {
  const [input, setInput] = useState("");
  const [parts, total] = (session.progress ?? "1/1").split("/").map(Number);

  const progress = parts / total;

  function submit() {
    const ans = input.trim();
    onAnswer(ans);
    setInput("");
  }

  return (
    <div className="space-y-6">
      {/* Progress bar */}
      <div>
        <div className="flex items-center justify-between mb-2 text-xs text-muted">
          <span>Step {parts} of {total}</span>
          <span className="font-mono">{Math.round(progress * 100)}%</span>
        </div>
        <div className="h-1.5 rounded-full bg-bg-elevated overflow-hidden">
          <div
            className="h-full rounded-full bg-accent transition-all duration-500"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
      </div>

      {/* Question card */}
      <div className="p-5 rounded-xl bg-bg-elevated border border-bg-border space-y-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-accent-light px-2 py-0.5 bg-accent/10 rounded border border-accent/20">
            {session.field}
          </span>
          {!session.required && (
            <Badge variant="muted" size="sm">optional</Badge>
          )}
        </div>

        <p className="text-sm font-medium text-white">{session.question}</p>

        {session.hint && (
          <p className="text-xs text-muted italic border-l-2 border-bg-border pl-3">{session.hint}</p>
        )}

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={session.placeholder ?? "Type your answer…"}
          rows={4}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === "Enter" && e.metaKey) submit();
          }}
          className="w-full px-3 py-2.5 text-sm bg-bg-surface border border-bg-border rounded-lg text-white placeholder-muted focus:outline-none focus:border-accent/50 resize-none"
        />

        {session.example && (
          <div className="text-[11px] text-muted">
            <span className="text-muted/60">Example: </span>{session.example}
          </div>
        )}

        {session.error && (
          <p className="text-xs text-danger">{session.error}</p>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={submit}
          disabled={isLoading || (session.required && !input.trim())}
          className="flex items-center gap-2 px-5 py-2.5 text-sm font-medium bg-accent hover:bg-accent/80 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg transition-colors"
        >
          {isLoading ? (
            <RefreshCw size={14} className="animate-spin" />
          ) : (
            <ArrowRight size={14} />
          )}
          Continue
        </button>

        {!session.required && (
          <button
            onClick={onSkip}
            className="px-4 py-2.5 text-sm text-muted hover:text-white border border-bg-border hover:border-bg-hover rounded-lg transition-colors"
          >
            Skip optional
          </button>
        )}

        <div className="flex-1" />
        <button
          onClick={onAbandon}
          className="px-3 py-2 text-xs text-muted/60 hover:text-danger transition-colors"
        >
          Abandon session
        </button>
      </div>
    </div>
  );
}

interface CompletionUIProps {
  session: PromptSession;
  onReset: () => void;
}

function CompletionUI({ session, onReset }: CompletionUIProps) {
  const [copied, setCopied] = useState(false);

  function copyPrompt() {
    if (session.prompt) {
      navigator.clipboard.writeText(session.prompt).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 p-4 rounded-xl bg-success-dim border border-success/20">
        <CheckCircle2 size={18} className="text-success shrink-0" />
        <div>
          <div className="text-sm font-semibold text-white">Prompt assembled!</div>
          <div className="text-xs text-muted">
            {session.field_count} fields · Skill: <span className="font-mono text-accent-light">{session.skill_to_invoke}</span>
          </div>
        </div>
      </div>

      <div className="relative">
        <div className="absolute top-3 right-3">
          <button
            onClick={copyPrompt}
            className="text-xs text-muted hover:text-white px-2.5 py-1 bg-bg-elevated border border-bg-border rounded transition-colors"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
        </div>
        <pre className="p-4 rounded-xl bg-bg-elevated border border-bg-border text-xs text-white/80 whitespace-pre-wrap leading-relaxed max-h-64 overflow-y-auto font-mono">
          {session.prompt}
        </pre>
      </div>

      <div className="p-4 rounded-xl bg-accent/10 border border-accent/20">
        <p className="text-xs text-accent-light font-medium mb-1">Next Step</p>
        <p className="text-xs text-white/70">
          Invoke the <code className="font-mono text-accent-light">/{session.skill_to_invoke}</code> skill with this prompt as the task to run the full workflow.
        </p>
      </div>

      <button
        onClick={onReset}
        className="flex items-center gap-2 text-xs text-muted hover:text-white transition-colors"
      >
        <RotateCcw size={12} />
        Start new prompt
      </button>
    </div>
  );
}

export function PromptBuilder() {
  const { data: templates, isLoading } = usePromptTemplates();
  const [session, setSession] = useState<PromptSession | null>(null);
  const [isWorking, setWorking] = useState(false);

  async function startSession(templateName: string) {
    setWorking(true);
    try {
      const s = await api.startSession(templateName);
      setSession(s);
    } finally {
      setWorking(false);
    }
  }

  async function answer(ans: string) {
    if (!session?.session_id) return;
    setWorking(true);
    try {
      const s = await api.answerField(session.session_id, ans);
      setSession(s);
    } finally {
      setWorking(false);
    }
  }

  async function skip() {
    if (!session?.session_id) return;
    setWorking(true);
    try {
      const s = await api.skipField(session.session_id);
      setSession(s);
    } finally {
      setWorking(false);
    }
  }

  async function abandon() {
    if (!session?.session_id) return;
    await api.abandonSession(session.session_id);
    setSession(null);
  }

  return (
    <div className="p-6 space-y-6 animate-fade-in">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-xl bg-accent/15 border border-accent/25 flex items-center justify-center">
          <Sparkles size={18} className="text-accent-light" />
        </div>
        <div>
          <h2 className="text-base font-semibold text-white">Prompt Builder</h2>
          <p className="text-xs text-muted">
            Build structured, high-quality prompts from templates — then auto-invoke the right skill
          </p>
        </div>
      </div>

      {!session ? (
        <Card>
          <CardHeader>
            <CardTitle>Choose a Template</CardTitle>
            <span className="text-xs text-muted">{templates?.length ?? 0} templates</span>
          </CardHeader>
          <CardBody>
            {isLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {Array.from({ length: 6 }).map((_, i) => (
                  <div key={i} className="h-32 rounded-xl bg-bg-elevated animate-pulse" />
                ))}
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {(templates ?? []).map((t) => (
                  <TemplateCard
                    key={t.name}
                    template={t}
                    onSelect={() => startSession(t.name)}
                  />
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      ) : session.status === "complete" ? (
        <Card>
          <CardHeader>
            <CardTitle icon={<CheckCircle2 size={14} />}>
              {session.template?.replace(/_/g, " ")}
            </CardTitle>
          </CardHeader>
          <CardBody>
            <CompletionUI session={session} onReset={() => setSession(null)} />
          </CardBody>
        </Card>
      ) : (
        <Card>
          <CardHeader>
            <CardTitle icon={<Sparkles size={14} />}>
              Building: {session.template?.replace(/_/g, " ")}
            </CardTitle>
            <button
              onClick={() => setSession(null)}
              className="text-xs text-muted hover:text-white transition-colors"
            >
              ← Templates
            </button>
          </CardHeader>
          <CardBody>
            <SessionUI
              session={session}
              onAnswer={answer}
              onSkip={skip}
              onAbandon={abandon}
              isLoading={isWorking}
            />
          </CardBody>
        </Card>
      )}
    </div>
  );
}
