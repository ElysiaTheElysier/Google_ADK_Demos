import { useMemo, useRef, useState } from 'react'
import {
  Activity, ArrowRight, Braces, Check, ChevronDown, CircleStop,
  Clipboard, Clock3, Cpu, ExternalLink, Globe, Play, RotateCcw, ShieldCheck, Sparkles, TerminalSquare, X,
} from 'lucide-react'

type Status = 'idle' | 'running' | 'completed' | 'failed'
type TraceEvent = { event: string; data: Record<string, any>; receivedAt: number }
type NodeRun = {
  id: string; label: string; eyebrow: string; status: Status; start?: number; end?: number
  input?: unknown; output?: unknown; usage?: Usage; metadata?: unknown
}
type Usage = { input: number; output: number; total: number; calls?: number }

const evaluatorIds = ['clarity_evaluator', 'context_evaluator', 'constraints_evaluator', 'format_evaluator']
const promptifyTopics = [
  { value: 'auto', label: 'Auto-match Promptify Lab' },
  { value: 'Lab 01: PII Scrubbing & Data Privacy', label: 'Lab 01 · PII Scrubbing & Data Privacy' },
  { value: 'Lab 02: Context Engineering & Few-Shot', label: 'Lab 02 · Context Engineering & Few-Shot' },
  { value: 'Lab 03: Multi-Step CoT & Guardrails', label: 'Lab 03 · Multi-Step CoT & Guardrails' },
  { value: 'Lab 04: ReAct & Agentic Workflow', label: 'Lab 04 · ReAct & Agentic Workflow' },
  { value: 'Lab 05: Temperature & Generation Control', label: 'Lab 05 · Temperature & Generation Control' },
  { value: 'Lab 07: Prompt Injection Defense & Grounding', label: 'Lab 07 · Prompt Injection Defense' },
  { value: 'Lab 08: Step-Back & Meta-Prompting', label: 'Lab 08 · Step-Back & Meta-Prompting' },
]
const nodeSeed: NodeRun[] = [
  { id: 'user', label: 'User prompt', eyebrow: 'INPUT', status: 'idle' },
  { id: 'prompt_analyzer', label: 'Prompt analyzer', eyebrow: 'LLM AGENT', status: 'idle' },
  { id: 'clarity_evaluator', label: 'Clarity', eyebrow: 'PARALLEL', status: 'idle' },
  { id: 'context_evaluator', label: 'Context', eyebrow: 'PARALLEL', status: 'idle' },
  { id: 'constraints_evaluator', label: 'Constraints', eyebrow: 'PARALLEL', status: 'idle' },
  { id: 'format_evaluator', label: 'Output format', eyebrow: 'PARALLEL', status: 'idle' },
  { id: 'context_enricher', label: 'Context enricher', eyebrow: 'LLM + TOOL', status: 'idle' },
  { id: 'evaluation_join', label: 'Join', eyebrow: 'CONTROL', status: 'idle' },
  { id: 'final_reviewer', label: 'Final reviewer', eyebrow: 'LLM AGENT', status: 'idle' },
  { id: 'response_generator', label: 'Response generator', eyebrow: 'LLM AGENT', status: 'idle' },
  { id: 'promptify_validator_agent', label: 'Promptify validator', eyebrow: 'EXTERNAL', status: 'idle' },
]

const samples = [
  {
    label: 'Good prompt',
    value: 'Write a 500-word product launch blog post for Remi, an AI note-taking app for university students. Use an enthusiastic but professional tone. Highlight automatic lecture transcription, searchable notes, and weekly summaries. Structure the response with a headline, short introduction, three feature sections, and a final call to action inviting readers to join the free beta. Do not invent pricing or availability dates.',
  },
  {
    label: 'Weak prompt',
    value: 'Write something good about our new app.',
  },
  {
    label: 'Needs search',
    value: 'Create a concise technical explainer for a junior AI engineer about retrieval-augmented generation. Verify its origin using public sources, explain the retriever, knowledge store, and generator, then provide a short timeline and include source links. Use clear headings and stay under 700 words.',
  },
  {
    label: 'No search',
    value: 'Rewrite this internal announcement in a warm, concise tone for our product team: Remi private beta starts next Monday for the 20 invited testers. Keep all facts exactly as provided, use one short paragraph followed by three bullet points, and do not add external information.',
  },
]

const parseMaybeJson = (value: unknown) => {
  if (typeof value !== 'string') return value
  try { return JSON.parse(value) } catch { return value }
}
const fmt = (n?: number) => n == null ? '—' : `${n.toFixed(2)}s`
const clock = (n?: number) => n ? new Date(n * 1000).toLocaleTimeString([], { hour12: false }) : '—'

function App() {
  const [prompt, setPrompt] = useState(samples[0].value)
  const [nodes, setNodes] = useState<NodeRun[]>(nodeSeed)
  const [events, setEvents] = useState<TraceEvent[]>([])
  const [selected, setSelected] = useState('prompt_analyzer')
  const [running, setRunning] = useState(false)
  const [sessionId, setSessionId] = useState('not started')
  const [model, setModel] = useState('gemini-3.5-flash-lite')
  const [fallbackFrom, setFallbackFrom] = useState<string>()
  const [totalRuntime, setTotalRuntime] = useState<number>()
  const [usage, setUsage] = useState<Usage>({ input: 0, output: 0, total: 0, calls: 0 })
  const [state, setState] = useState<unknown>({})
  const [error, setError] = useState<string>()
  const [temperature, setTemperature] = useState(0)
  const [researchEnabled, setResearchEnabled] = useState(false)
  const [validating, setValidating] = useState(false)
  const [validationTopic, setValidationTopic] = useState('auto')
  const abortController = useRef<AbortController | null>(null)

  const branchIds = useMemo(
    () => researchEnabled ? [...evaluatorIds, 'context_enricher'] : evaluatorIds,
    [researchEnabled],
  )

  const patchNode = (id: string, patch: Partial<NodeRun>) =>
    setNodes(current => current.map(node => node.id === id ? { ...node, ...patch } : node))

  const handleMessage = (message: TraceEvent, activeBranchIds: string[]) => {
    setEvents(current => [...current, message])
    const d = message.data
    if (message.event === 'run.started') {
      setSessionId(d.sessionId); setModel(d.model)
    }
    if (message.event === 'run.fallback') {
      setFallbackFrom(d.fromModel)
      setModel(d.toModel)
      setError(undefined)
      if (d.scope !== 'validation') {
        setNodes(nodeSeed)
        setUsage({ input: 0, output: 0, total: 0, calls: 0 })
      }
    }
    if (message.event === 'node.started' || message.event === 'validation.started') {
      patchNode(d.node, { status: 'running', start: d.at, input: parseMaybeJson(d.input) })
    }
    if (message.event === 'adk.event') {
      setNodes(current => current.map(node => {
        if (node.id !== d.node) return node
        const prevMeta = (node.metadata ?? {}) as Record<string, any>
        const nextMeta = (d.metadata ?? {}) as Record<string, any>
        const mergedTools = nextMeta.tools?.length ? nextMeta.tools : (prevMeta.tools ?? [])
        const mergedUsage = d.usage?.total ? d.usage : (node.usage ?? d.usage)
        return {
          ...node,
          metadata: { ...prevMeta, ...nextMeta, tools: mergedTools },
          usage: mergedUsage,
        }
      }))
    }
    if (message.event === 'node.completed' || message.event === 'validation.completed') {
      setNodes(current => {
        const completedAt = d.at ?? Date.now() / 1000
        const parsedOut = parseMaybeJson(d.output) as any
        const nextStatus: Status = message.event === 'validation.completed' && parsedOut?.status === 'failed'
          ? 'failed'
          : 'completed'
        let updated = current.map(node => {
          if (node.id !== d.node) return node
          const prevMeta = (node.metadata ?? {}) as Record<string, any>
          const nextMeta = (d.metadata ?? {}) as Record<string, any>
          const mergedTools = nextMeta.tools?.length ? nextMeta.tools : (prevMeta.tools ?? [])
          return {
            ...node,
            status: nextStatus,
            end: completedAt,
            output: parsedOut,
            usage: d.usage?.total ? d.usage : (node.usage ?? d.usage),
            metadata: Object.keys(nextMeta).length || Object.keys(prevMeta).length
              ? { ...prevMeta, ...nextMeta, tools: mergedTools }
              : node.metadata,
          }
        })

        // Reconstruct JoinNode state once all parallel branches finish.
        const branches = updated.filter(node => activeBranchIds.includes(node.id))
        if (
          activeBranchIds.includes(d.node)
          && branches.length === activeBranchIds.length
          && branches.every(node => node.status === 'completed' && node.output != null)
        ) {
          const joinedOutput = Object.fromEntries(
            branches.map(node => [node.id, node.output]),
          )
          const joinStart = Math.max(...branches.map(node => node.end ?? completedAt))
          updated = updated.map(node => node.id === 'evaluation_join' ? {
            ...node,
            status: 'completed' as Status,
            start: node.start ?? joinStart,
            end: completedAt,
            input: joinedOutput,
            output: joinedOutput,
          } : node)
        }
        return updated
      })
      if (message.event === 'validation.completed') {
        setValidating(false)
        setState((prev: any) => ({ ...(prev ?? {}), external_validation: parseMaybeJson(d.output) }))
      }
    }
    if (message.event === 'run.completed') {
      setNodes(current => {
        const branchState = Object.fromEntries(
          current
            .filter(node => activeBranchIds.includes(node.id))
            .map(node => [node.id, node.output]),
        )
        const hasJoinedState = Object.values(branchState).every(value => value != null)
        return current.map(node => {
          if (node.id === 'evaluation_join' && node.status === 'idle' && hasJoinedState) {
            const at = Date.now() / 1000
            return { ...node, status: 'completed', start: at, end: at, input: branchState, output: branchState }
          }
          return node.status === 'running'
            ? { ...node, status: 'completed', end: Date.now() / 1000 }
            : node
        })
      })
      setTotalRuntime(d.duration); setUsage(d.usage); setState(d.state); setRunning(false)
    }
    if (message.event === 'run.failed') {
      setTotalRuntime(d.duration); setError(d.error); setRunning(false)
      setNodes(current => current.map(n => n.status === 'running' ? { ...n, status: 'failed', end: Date.now() / 1000 } : n))
    }
  }

  const run = async () => {
    if (running) {
      abortController.current?.abort()
      return
    }
    if (!prompt.trim()) return
    const activeBranchIds = researchEnabled ? [...evaluatorIds, 'context_enricher'] : evaluatorIds
    setNodes(nodeSeed); setEvents([]); setError(undefined); setTotalRuntime(undefined); setFallbackFrom(undefined)
    setUsage({ input: 0, output: 0, total: 0, calls: 0 }); setState({}); setRunning(true)
    const controller = new AbortController()
    abortController.current = controller
    try {
      const response = await fetch('http://localhost:8000/api/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, temperature, enable_research: researchEnabled }),
        signal: controller.signal,
      })
      if (!response.ok || !response.body) throw new Error(`Backend returned ${response.status}`)
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''
      while (true) {
        const { value, done } = await reader.read(); if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n'); buffer = lines.pop() ?? ''
        for (const line of lines) if (line.trim()) handleMessage({ ...JSON.parse(line), receivedAt: Date.now() }, activeBranchIds)
      }
    } catch (e) {
      const cancelled = e instanceof DOMException && e.name === 'AbortError'
      setError(cancelled ? 'Run cancelled by user.' : e instanceof Error ? e.message : String(e)); setRunning(false)
      setNodes(current => current.map(n => n.status === 'running' ? { ...n, status: 'failed', end: Date.now() / 1000 } : n))
    } finally {
      abortController.current = null
    }
  }

  const validatePromptify = async (improvedPrompt: string) => {
    if (validating || !improvedPrompt.trim()) return
    setValidating(true)
    setSelected('promptify_validator_agent')
    const activeBranchIds = researchEnabled ? [...evaluatorIds, 'context_enricher'] : evaluatorIds
    try {
      const response = await fetch('http://localhost:8000/api/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: improvedPrompt, topic: validationTopic }),
      })
      if (!response.ok || !response.body) throw new Error(`Validation endpoint returned ${response.status}`)
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''
      while (true) {
        const { value, done } = await reader.read(); if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n'); buffer = lines.pop() ?? ''
        for (const line of lines) if (line.trim()) handleMessage({ ...JSON.parse(line), receivedAt: Date.now() }, activeBranchIds)
      }
    } catch (e) {
      patchNode('promptify_validator_agent', {
        status: 'failed',
        end: Date.now() / 1000,
        output: {
          status: 'failed',
          submitted_prompt: improvedPrompt,
          topic: validationTopic,
          score: null,
          feedback: [e instanceof Error ? e.message : String(e)],
          result_url: 'https://promptify-wheat-seven.vercel.app/',
        },
      })
    } finally {
      setValidating(false)
    }
  }

  const chosen = nodes.find(n => n.id === selected) ?? nodes[0]
  const final = parseMaybeJson(nodes.find(n => n.id === 'final_reviewer')?.output) as any
  const enrichment = parseMaybeJson(nodes.find(n => n.id === 'context_enricher')?.output) as any
  const generatedResponse = parseMaybeJson(nodes.find(n => n.id === 'response_generator')?.output) as any
  const externalValidation = parseMaybeJson(nodes.find(n => n.id === 'promptify_validator_agent')?.output) as any
  const enricherNode = nodes.find(n => n.id === 'context_enricher')!
  const validatorNode = nodes.find(n => n.id === 'promptify_validator_agent')!
  const evaluatorWindow = useMemo(() => {
    const runs = nodes.filter(n => branchIds.includes(n.id) && n.start)
    const min = Math.min(...runs.map(n => n.start!)); const max = Math.max(...runs.map(n => n.end ?? n.start!))
    return Number.isFinite(min) ? { min, span: Math.max(max - min, .1) } : undefined
  }, [nodes, branchIds])

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><div className="brand-mark"><Braces size={17}/></div><div><strong>Prompt Inspector</strong><span>Google ADK runtime</span></div></div>
      <div className="metrics">
        <Metric label={fallbackFrom ? 'MODEL (FALLBACK)' : 'MODEL'} value={model.replace('gemini-', '')}/><Metric label="RUNTIME" value={fmt(totalRuntime)}/>
        <Metric label="CALLS" value={String(usage.calls ?? 0)}/><Metric label="TOKENS" value={usage.total.toLocaleString()}/>
      </div>
      <div className={`run-pill ${running || validating ? 'live' : ''}`}><i/>{running ? 'Live run' : validating ? 'Validating...' : totalRuntime ? 'Run complete' : 'Ready'}</div>
    </header>

    <main>
      <section className="hero-grid">
        <div className="prompt-pane">
          <div className="section-label"><Sparkles size={14}/> Prompt editor</div>
          <h1>Evaluate the prompt.<br/><span>Inspect every decision.</span></h1>
          <p className="lede">Run a structured multi-agent review and watch Google ADK coordinate analysis, parallel evaluation, tool calling, and synthesis.</p>
          <div className="editor">
            <textarea value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="Paste a prompt to evaluate..." />
            <div className="editor-footer"><span>{prompt.length} characters</span><button className={`run-button ${running ? 'stop' : ''}`} onClick={run} disabled={!running && !prompt.trim()}>{running ? <CircleStop size={16}/> : <Play size={16} fill="currentColor"/>}{running ? 'Stop run' : 'Run evaluation'}</button></div>
          </div>
          <label className="research-toggle"><input type="checkbox" checked={researchEnabled} onChange={e => setResearchEnabled(e.target.checked)} disabled={running}/><span><strong>Enrich with public search</strong><small>Adds the Context Enricher LLM agent to the parallel fan-out. It decides whether public facts are needed and calls search_public_context itself.</small></span></label>
          <div className="temperature-control">
            <div><span>Temperature</span><strong>{temperature.toFixed(1)}</strong></div>
            <input aria-label="Model temperature" type="range" min="0" max="1" step="0.1" value={temperature} onChange={e => setTemperature(Number(e.target.value))} disabled={running}/>
            <small>{temperature === 0 ? 'Most consistent' : temperature <= .3 ? 'Low variation' : temperature <= .7 ? 'Balanced' : 'More variation'}</small>
          </div>
          <div className="samples"><span>Try a sample</span>{samples.map(s => <button key={s.label} onClick={() => setPrompt(s.value)}>{s.label}</button>)}</div>
          {error && <div className="error-banner"><X size={16}/><div><strong>Run failed</strong><p>{error}</p></div></div>}
        </div>

        <div className="workflow-pane">
          <div className="pane-heading"><div><div className="section-label"><Activity size={14}/> Workflow inspector</div><h2>Execution graph</h2></div><span className="session">SESSION {sessionId.slice(0, 8)}</span></div>
          <Workflow nodes={nodes} selected={selected} onSelect={setSelected} researchEnabled={researchEnabled}/>
          <div className="parallel-note"><Cpu size={15}/><span>{researchEnabled ? 'Parallel fan-out × 5' : 'Parallel fan-out × 4'}</span><p>{researchEnabled ? 'Four evaluators and the Context Enricher LLM agent run concurrently; Context Enricher decides when to call search_public_context.' : 'Public search is disabled; four evaluators run concurrently without external tool access.'}</p></div>
          <div className="optional-capabilities">
            <span className="optional-label">OPTIONAL CAPABILITIES</span>
            <div className="optional-grid">
              <button className={`optional-card ${selected === 'context_enricher' ? 'selected' : ''}`} onClick={() => setSelected('context_enricher')}>
                <div><Globe size={14}/><strong>Context Enricher</strong></div>
                <small>{!researchEnabled ? 'disabled' : enricherNode.status === 'completed' ? (enrichment?.used_search ? 'completed · searched' : 'completed · skipped') : enricherNode.status}</small>
              </button>
              <button className={`optional-card ${selected === 'promptify_validator_agent' ? 'selected' : ''}`} onClick={() => setSelected('promptify_validator_agent')}>
                <div><ShieldCheck size={14}/><strong>Promptify Validator</strong></div>
                <small>{externalValidation?.status ? externalValidation.status.replace('_', ' ') : validatorNode.status}</small>
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="workspace-grid">
        <div className="results-column">
          <div className="section-heading"><div><span>Evaluation output</span><h2>{final ? 'Review completed' : 'Results will appear here'}</h2></div>{final?.overall_score && <div className="score"><strong>{final.overall_score}</strong><span>/ 5<br/>overall</span></div>}</div>
          {final ? <FinalResult result={final} original={prompt} generated={generatedResponse} enrichment={researchEnabled ? enrichment : undefined} externalValidation={externalValidation} validating={validating} validationTopic={validationTopic} onChangeTopic={setValidationTopic} onValidate={() => validatePromptify(final.improved_prompt)}/> : <div className="empty-state"><div><RotateCcw size={20}/></div><p>Run an evaluation to see criterion scores, findings, suggestions, and an improved prompt.</p></div>}
        </div>
        <aside className="inspector">
          <div className="inspector-head"><div><span>{chosen.eyebrow}</span><h2>{chosen.label}</h2></div><StatusBadge status={chosen.status}/></div>
          <div className="inspector-stats"><div><span>START</span><strong>{clock(chosen.start)}</strong></div><div><span>LATENCY</span><strong>{chosen.start && chosen.end ? fmt(chosen.end - chosen.start) : '—'}</strong></div><div><span>TOKENS</span><strong>{chosen.usage?.total ?? '—'}</strong></div></div>
          <InspectorBlock title="Input" value={chosen.input}/>
          <InspectorBlock title="Structured output" value={chosen.output}/>
          <InspectorBlock title="Event metadata" value={chosen.metadata} forceOpen={chosen.id === 'context_enricher' || chosen.id === 'promptify_validator_agent'}/>
        </aside>
      </section>

      <section className="observability-grid">
        <div className="timeline-panel">
          <div className="panel-title"><div><Clock3 size={15}/><span>Parallel timeline</span></div><small>WALL-CLOCK VIEW</small></div>
          {branchIds.map(id => { const n = nodes.find(x => x.id === id)!; const left = evaluatorWindow && n.start ? ((n.start-evaluatorWindow.min)/evaluatorWindow.span)*100 : 0; const width = evaluatorWindow && n.start ? (((n.end ?? Date.now()/1000)-n.start)/evaluatorWindow.span)*100 : 0; return <div className="lane" key={id}><span>{n.label}</span><div className="track"><i className={n.status} style={{left:`${left}%`,width:`${Math.max(width, n.status === 'running' ? 4 : 0)}%`}}/></div><b>{n.start && n.end ? fmt(n.end-n.start) : n.status}</b></div> })}
        </div>
        <div className="console-panel">
          <div className="panel-title"><div><TerminalSquare size={15}/><span>Trace console</span></div><small>{events.length} EVENTS</small></div>
          <div className="console-body">{events.length ? events.slice().reverse().map((e, i) => <details key={`${e.receivedAt}-${i}`}><summary><time>{new Date(e.receivedAt).toLocaleTimeString([], {hour12:false})}</time><code>{e.data.node ?? 'runner'}</code><span>{e.event.replace('.', ' ')}</span><ChevronDown size={13}/></summary><pre>{JSON.stringify(e.data, null, 2)}</pre></details>) : <div className="console-empty">Waiting for the first execution event...</div>}</div>
        </div>
      </section>
      <details className="state-drawer"><summary>Developer state <ChevronDown size={14}/></summary><pre>{JSON.stringify(state, null, 2)}</pre></details>
    </main>
  </div>
}

function Metric({label,value}:{label:string,value:string}) { return <div className="metric"><span>{label}</span><strong>{value}</strong></div> }
function StatusBadge({status}:{status:Status}) { return <span className={`status-badge ${status}`}><i/>{status}</span> }
function NodeCard({node,selected,onClick,className=''}:{node:NodeRun;selected:boolean;onClick:()=>void;className?:string}) {
  const duration = node.status === 'completed' && node.start && node.end ? fmt(node.end - node.start) : node.status
  const out = node.output as Record<string, any> | undefined
  const detail = node.id === 'context_enricher' && node.status === 'completed' && out && typeof out.used_search === 'boolean'
    ? `${duration} · ${out.used_search ? 'searched' : 'skipped'}`
    : duration
  return <button className={`node-card ${node.status} ${selected?'selected':''} ${className}`.trim()} onClick={onClick}><span>{node.eyebrow}</span><strong>{node.label}</strong><small>{detail}</small><i className="node-state">{node.status === 'completed' && <Check size={11}/>}</i></button>
}
function Connector({active=false}:{active?:boolean}) { return <div className={`connector ${active?'active':''}`}><i/><ArrowRight size={14}/></div> }
function Workflow({nodes,selected,onSelect,researchEnabled}:{nodes:NodeRun[];selected:string;onSelect:(id:string)=>void;researchEnabled:boolean}) {
  const n=(id:string)=>nodes.find(x=>x.id===id)!
  const branchIds = researchEnabled ? [...evaluatorIds, 'context_enricher'] : evaluatorIds
  return <div className="flow">
    <NodeCard node={n('user')} selected={selected==='user'} onClick={()=>onSelect('user')}/>
    <Connector active={n('prompt_analyzer').status==='running'}/>
    <NodeCard node={n('prompt_analyzer')} selected={selected==='prompt_analyzer'} onClick={()=>onSelect('prompt_analyzer')}/>
    <Connector active={branchIds.some(id=>n(id).status==='running')}/>
    <div className="fanout">
      <span className="fanout-label">PARALLEL × {branchIds.length}</span>
      {evaluatorIds.map(id=><NodeCard key={id} node={n(id)} selected={selected===id} onClick={()=>onSelect(id)}/>)}
      {researchEnabled && <NodeCard node={n('context_enricher')} selected={selected==='context_enricher'} onClick={()=>onSelect('context_enricher')} className="fanout-wide"/>}
    </div>
    <Connector active={n('evaluation_join').status==='running'}/>
    <NodeCard node={n('evaluation_join')} selected={selected==='evaluation_join'} onClick={()=>onSelect('evaluation_join')}/>
    <Connector active={n('final_reviewer').status==='running'}/>
    <NodeCard node={n('final_reviewer')} selected={selected==='final_reviewer'} onClick={()=>onSelect('final_reviewer')}/>
    <Connector active={n('response_generator').status==='running'}/>
    <NodeCard node={n('response_generator')} selected={selected==='response_generator'} onClick={()=>onSelect('response_generator')}/>
  </div>
}
function InspectorBlock({title,value,forceOpen=false}:{title:string;value:unknown;forceOpen?:boolean}) { return <details className="inspect-block" open={forceOpen || title!=='Event metadata'}><summary>{title}<ChevronDown size={14}/></summary><pre>{value == null ? 'No data yet.' : typeof value === 'string' ? value : JSON.stringify(value,null,2)}</pre></details> }
function FinalResult({result,original,generated,enrichment,externalValidation,validating,validationTopic,onChangeTopic,onValidate}:{result:any;original:string;generated:any;enrichment?:any;externalValidation?:any;validating:boolean;validationTopic:string;onChangeTopic:(t:string)=>void;onValidate:()=>void}) {
  const [copied,setCopied]=useState(false)
  const evaluations=result.evaluations??[]
  return <div className="result-body">
    <p className="summary">{result.summary}</p>
    <div className="criterion-grid">{evaluations.map((e:any)=><details key={e.criterion}><summary><div><span>{e.criterion}</span><strong>{e.score}<small>/5</small></strong></div><ChevronDown size={15}/></summary><h4>Findings</h4><ul>{e.findings?.map((x:string)=><li key={x}>{x}</li>)}</ul><h4>Suggestions</h4><ul>{e.suggestions?.map((x:string)=><li key={x}>{x}</li>)}</ul></details>)}</div>
    {enrichment && <div className={`enrichment-panel ${enrichment.used_search ? 'used' : 'skipped'}`}>
      <div className="enrichment-head">
        <div><Globe size={14}/><span>CONTEXT ENRICHER</span><strong>{enrichment.used_search ? 'Public search executed' : 'Public search skipped'}</strong></div>
        {enrichment.search_query && <code>query: "{enrichment.search_query}"</code>}
      </div>
      <p className="enrichment-note">{enrichment.note}</p>
      {enrichment.useful_context?.length > 0 && <ul className="enrichment-facts">{enrichment.useful_context.map((fact:string, idx:number)=><li key={idx}>{fact}</li>)}</ul>}
      {enrichment.sources?.length > 0 && <div className="enrichment-sources">{enrichment.sources.map((src:any, idx:number)=><a key={idx} href={src.url} target="_blank" rel="noreferrer" className="source-chip"><ExternalLink size={12}/><span>{src.title}</span></a>)}</div>}
    </div>}
    <div className="prompt-compare">
      <div><span>ORIGINAL</span><p>{original}</p></div>
      <div className="improved">
        <span>IMPROVED</span>
        <p>{result.improved_prompt}</p>
        <div className="improved-actions">
          <button onClick={()=>{navigator.clipboard.writeText(result.improved_prompt);setCopied(true);setTimeout(()=>setCopied(false),1500)}}><Clipboard size={14}/>{copied?'Copied':'Copy improved prompt'}</button>
          <select aria-label="Promptify topic" value={validationTopic} onChange={e=>onChangeTopic(e.target.value)} disabled={validating}>
            {promptifyTopics.map(t=><option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
          <button className="validate-button" onClick={onValidate} disabled={validating}><ShieldCheck size={14}/>{validating?'Validating on Promptify...':externalValidation?.status==='login_required'?'Continue after Google login':'Validate with Promptify'}</button>
        </div>
      </div>
    </div>
    {externalValidation && <div className={`validation-panel ${externalValidation.status}`}>
      <div className="validation-head">
        <div>
          <ShieldCheck size={15}/>
          <span>EXTERNAL VALIDATION · PROMPTIFY</span>
          <strong>{externalValidation.status === 'login_required' ? 'Complete Google login in browser window' : externalValidation.status === 'completed' ? 'External score received' : externalValidation.status === 'running' ? 'Running in browser...' : 'Validation failed'}</strong>
        </div>
        {externalValidation.score != null && <div className="validation-score"><strong>{externalValidation.score}</strong><span>/ 10</span></div>}
      </div>
      <div className="validation-meta">
        <span>Topic: <b>{externalValidation.topic}</b></span>
        {externalValidation.result_url && <a href={externalValidation.result_url} target="_blank" rel="noreferrer"><ExternalLink size={12}/><span>Open Promptify</span></a>}
      </div>
      {externalValidation.feedback?.length > 0 && <ul className="validation-feedback">{externalValidation.feedback.map((item:string, idx:number)=><li key={idx}>{item}</li>)}</ul>}
    </div>}
    {generated&&<div className="generated-output"><span>FINAL LLM RESPONSE</span><p>{typeof generated==='string'?generated:JSON.stringify(generated,null,2)}</p></div>}
  </div>
}

export default App
