/**
 * Model-facing tool declarations for dsh-plugin-kde-uia.
 *
 * The declarations are built with `defineTool` from `@deepseek-ai/dsh-tools`,
 * the same route built-in tool plugins use, so schemas, argument validation
 * and result rendering behave exactly like first-party tools. Each tool is a
 * thin, typed adapter over one `kde_uia` operation:
 *
 * | tool          | client op   | effect |
 * |---------------|-------------|--------|
 * | `kde_uia_doctor`    | doctor      | reads capabilities, starts nothing |
 * | `kde_uia_windows`   | windows     | lists windows |
 * | `kde_uia_tree`      | tree        | prints one window/element tree |
 * | `kde_uia_find`      | find        | resolves elements to refs |
 * | `kde_uia_info`      | info        | properties/states/actions of a ref |
 * | `kde_uia_click`     | click       | clicks pointer or runs the a11y action |
 * | `kde_uia_keys`      | press       | key combination |
 * | `kde_uia_type`      | type        | types into the focused widget |
 * | `kde_uia_set_value` | set         | Value / editable-text assignment |
 * | `kde_uia_scroll`    | scroll      | wheel at a point/element |
 * | `kde_uia_wait_for`  | wait        | polls until element/window state changes |
 * | `kde_uia_screenshot`| screenshot  | captures the desktop/window/element |
 * | `kde_uia_activate`  | activate    | activates or manages one window |
 *
 * Mutating tools are marked `mutating`; the plugin refuses `mutating` tools
 * when `readOnly: true` is configured.
 * @module dsh-plugin-kde-uia/tools
 */

/** Tool name prefix; every tool is `kde_uia_<verb>`. */
export const TOOL_PREFIX = 'kde_uia_'

/** JSON Schema for an element reference string. */
const REF = {
  type: 'string',
  description: 'Element reference from kde_uia_tree / kde_uia_find, e.g. "uia:1:kwrite:1/0/2". Refs are paths; re-find when the window changes.'
}

/** JSON Schema for a selector condition tree. */
const SELECTOR = {
  type: 'object',
  additionalProperties: false,
  description: 'Condition tree; every present field must match. Scope fields (window/app/window_id) restrict the search to one window.',
  properties: {
    role: { type: 'string', description: 'AT-SPI role, e.g. "push button", "entry", "text", "list item", "menu item", "check box".' },
    name: { type: 'string', description: 'Accessible name of the element.' },
    text: { type: 'string', description: 'Shorthand: matches the element name OR its value/text.' },
    description: { type: 'string', description: 'Accessible description.' },
    match: { type: 'string', enum: ['contains', 'exact', 'regex'], description: 'Text comparison (default: case-insensitive contains).' },
    case_sensitive: { type: 'boolean', description: 'Make text comparisons case-sensitive.' },
    states: {
      type: 'object',
      additionalProperties: true,
      description: 'Required state bits, e.g. {"focusable": true, "checked": false}.'
    },
    attributes: {
      type: 'object',
      additionalProperties: true,
      description: 'Required accessible attributes, e.g. {"tag": "button"}.'
    },
    window: { type: 'string', description: 'Scope: window title (substring, or per `match`).' },
    app: { type: 'string', description: 'Scope: application name, e.g. "dolphin".' },
    window_id: { type: 'string', description: 'Scope: exact window id from kde_uia_windows.' },
    depth: { type: 'integer', description: 'Search depth limit (default 40).' },
    limit: { type: 'integer', description: 'Stop after this many matches (default 200).' }
  }
}

function text(rendered) {
  return [{ type: 'text', text: rendered }]
}

function asJson(value) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function summaryLine(value) {
  if (!value || typeof value !== 'object') return String(value)
  const count = Array.isArray(value.windows) ? value.windows.length : Array.isArray(value.elements) ? value.elements.length : undefined
  const parts = []
  if (count !== undefined) parts.push(`${count} result${count === 1 ? '' : 's'}`)
  if (value.ok === false) parts.push('failed')
  if (value.hint) parts.push(String(value.hint))
  return parts.join(' — ') || asJson(value)
}

/**
 * Build every tool definition against one call function.
 *
 * @param {object} options
 * @param {Function} options.defineTool - `defineTool` from @deepseek-ai/dsh-tools
 * @param {(op: string, args: object, exec?: object) => Promise<any>} options.call - runs one client op, returns its result value or throws a coded error
 * @param {boolean} [options.readOnly] - when true, mutating tools are not registered
 * @returns {Array<object>} tool definitions
 */
/**
 * Map the `window-op` sentinel onto the client's real operations: `activate`
 * for the default action, `window` (with `op`) for the rest. Every other tool
 * op passes through untouched.
 */
export function windowOp(op, args) {
  if (op !== 'window-op') return { op, args }
  const action = args?.action ?? 'activate'
  const common = { window: args?.window, app: args?.app, id: args?.id }
  if (action === 'activate') return { op: 'activate', args: common }
  return {
    op: 'window',
    args: {
      ...common,
      op: action,
      ...(args?.x === undefined ? {} : { x: args.x }),
      ...(args?.y === undefined ? {} : { y: args.y }),
      ...(args?.width === undefined ? {} : { width: args.width }),
      ...(args?.height === undefined ? {} : { height: args.height })
    }
  }
}

export function buildTools({ defineTool, call, readOnly = false }) {
  /** Wrap an op with the standard renderer and error contract. */
  const tool = (name, description, parameters, op, mapArgs, render, flags = {}) => {
    if (readOnly && flags.mutating) return null
    return defineTool({
      name: `${TOOL_PREFIX}${name}`,
      description,
      parameters,
      output: {
        // Author-only `json`: the tool returns the client's JSON value as-is and
        // `render` turns it into the text the model reads.
        schema: { type: 'json' },
        render: (_args, value) => text(render(value))
      },
      async execute(args, exec) {
        if (readOnly && flags.mutating) {
          throw new Error(`kde_uia_${name} is disabled: this deployment configured readOnly: true`)
        }
        try {
          // `window-op` is not a client operation: it resolves to `activate`
          // or `window` (0.1.0 sent the sentinel verbatim and every window
          // action failed with "unknown op 'window-op'").
          const args_ = mapArgs(args)
          const planned = windowOp(op, args_)
          const value = await call(planned.op, planned.args, exec)
          return value
        } catch (error) {
        // Errors become `Error: <message>` results, like every built-in tool.
        const hint = error && error.hint ? `\nHint: ${error.hint}` : ''
        const detail = error && error.details ? `\nDetails: ${asJson(error.details)}` : ''
        throw new Error(`${error?.message ?? String(error)}${hint}${detail}`)
      }
    },
    presentCall: (args) => ({
      card: 'generic',
      title: `kde-uia ${name}`,
      // ToolPresentationKind offers only search | other; searches read, edits change state.
      kind: flags.mutating ? 'other' : 'search',
      rawInput: args
    })
    })
  }

  const tools = [
    tool(
      'doctor',
      'Check whether this DSH host can automate the Linux KDE desktop: transport (WSL/SSH), Python client, AT-SPI accessibility bus, window backend, input and screenshot backends. Start here when other kde_uia tools fail. Read-only.',
      {},
      'doctor',
      () => ({}),
      (v) => {
        const checks = Array.isArray(v?.checks) ? v.checks : []
        const lines = checks.map((c) => `${c.status === 'ok' ? '[+]' : c.status === 'skip' ? '[-]' : '[x]'} ${c.check}: ${c.detail}${c.hint ? `\n    hint: ${c.hint}` : ''}`)
        return `${v?.ok ? 'All capability checks passed.' : 'Some capability checks failed.'}\n${lines.join('\n')}`
      }
    ),
    tool(
      'windows',
      'List windows on the KDE desktop (accessibility windows merged with KWin/X11 window-manager windows) with title, application, ids and geometry. Read-only. Use the returned `ref` or `id` to scope later calls.',
      {
        include_hidden: { type: 'boolean', description: 'Include minimized/hidden windows (default false).' },
        window: { type: 'string', description: 'Only titles containing this text.' },
        app: { type: 'string', description: 'Only this application (substring).' },
        selector: SELECTOR
      },
      'windows',
      (a) => ({
        include_hidden: a.include_hidden === true,
        selector: {
          ...(a.selector ?? {}),
          ...(a.window === undefined ? {} : { window: a.window }),
          ...(a.app === undefined ? {} : { app: a.app })
        }
      }),
      (v) => {
        const rows = Array.isArray(v?.windows) ? v.windows : []
        if (!rows.length) return v?.hint ?? 'No windows found.'
        const body = rows.map((w) => {
          const frame = w.frame ?? w.extents ?? {}
          const geo = frame.width ? `${frame.width}x${frame.height}+${frame.x}+${frame.y}` : '?'
          return `${w.active ? '*' : ' '} ${String(w.id ?? w.ref ?? '').padEnd(12)} ${geo.padEnd(16)} ${String(w.app ?? '').padEnd(16)} ${w.title ?? ''}${w.source ? `  (${w.source})` : ''}`
        })
        return `${body.join('\n')}${v?.degraded ? `\nDegraded: ${v.degradedReason ?? ''}` : ''}`
      }
    ),
    tool(
      'tree',
      'Print one window (or an element) as an indented accessibility tree with roles, names, values, actions and `uia:` refs. Read-only; this is the main way to discover what to click.',
      {
        window: { type: 'string', description: 'Window title (substring).' },
        app: { type: 'string', description: 'Application name (substring).' },
        window_id: { type: 'string', description: 'Exact window id.' },
        ref: { ...REF, description: 'Start from this element instead of a whole window.' },
        depth: { type: 'integer', description: 'Maximum depth (default 4, raise to 6-8 for forms).' },
        max_nodes: { type: 'integer', description: 'Node budget (default 200).' },
        include_extents: { type: 'boolean', description: 'Append on-screen rectangles.' },
        selector: SELECTOR
      },
      'tree',
      (a) => ({
        ...(a.ref === undefined ? {} : { ref: a.ref }),
        depth: a.depth,
        max_nodes: a.max_nodes,
        include_extents: a.include_extents === true,
        selector: {
          ...(a.selector ?? {}),
          ...(a.window === undefined ? {} : { window: a.window }),
          ...(a.app === undefined ? {} : { app: a.app }),
          ...(a.window_id === undefined ? {} : { window_id: a.window_id })
        }
      }),
      (v) => {
        const head = v?.window ? `window: ${v.window.title ?? ''} [${v.window.app ?? ''}]  root=${v.rootRef ?? ''}` : ''
        return `${head}\n${v?.text ?? ''}${v?.truncated ? '\n(tree truncated; raise depth/max_nodes or pass a deeper ref)' : ''}`
      }
    ),
    tool(
      'find',
      'Find elements matching role/name/text/states, optionally scoped to one window. Returns `uia:` refs plus geometry. Read-only. Prefer role+text over coordinates: refs survive geometry changes but not widget insertions.',
      {
        role: { type: 'string', description: 'Role, e.g. "push button".' },
        text: { type: 'string', description: 'Matches name or value (case-insensitive contains by default).' },
        name: { type: 'string', description: 'Accessible name.' },
        match: { type: 'string', enum: ['contains', 'exact', 'regex'], description: 'Text comparison mode.' },
        window: { type: 'string', description: 'Scope: window title (substring).' },
        app: { type: 'string', description: 'Scope: application.' },
        window_id: { type: 'string', description: 'Scope: exact window id.' },
        actionable: { type: 'string', description: 'Item kind: button | link | checkbox | radio | textbox | menuitem | tab (omitted when the role is ambiguous).' },
        actionable_kind: { type: 'string', description: 'Alias of `actionable`.' },
        states: { type: 'object', additionalProperties: true, description: 'Required states.' },
        limit: { type: 'integer', description: 'Maximum matches (default 50).' },
        refs: { type: 'array', items: { type: 'string' }, description: 'Instead of searching: check these refs still resolve.' },
        selector: SELECTOR
      },
      'find',
      (a) => {
        const roles = {
          button: 'push button',
          link: 'link',
          checkbox: 'check box',
          radio: 'radio button',
          textbox: 'entry',
          menuitem: 'menu item',
          tab: 'page tab'
        }
        const kind = a.actionable ?? a.actionable_kind
        return {
          refs: a.refs,
          selector: {
            ...(a.selector ?? {}),
            ...(kind && roles[kind] ? { role: roles[kind] } : {}),
            ...(a.role === undefined ? {} : { role: a.role }),
            ...(a.text === undefined ? {} : { text: a.text }),
            ...(a.name === undefined ? {} : { name: a.name }),
            ...(a.match === undefined ? {} : { match: a.match }),
            ...(a.states === undefined ? {} : { states: a.states }),
            ...(a.limit === undefined ? {} : { limit: a.limit }),
            ...(a.window === undefined ? {} : { window: a.window }),
            ...(a.app === undefined ? {} : { app: a.app }),
            ...(a.window_id === undefined ? {} : { window_id: a.window_id })
          }
        }
      },
      (v) => {
        const rows = Array.isArray(v?.elements) ? v.elements : []
        if (!rows.length) return v?.hint ?? 'No matching elements.'
        const body = rows.map((e) => {
          const r = e.extents ?? {}
          return `${String(e.role).padEnd(16)} ${JSON.stringify(e.name ?? '').padEnd(32)} ${r.width ? `@${r.x},${r.y} ${r.width}x${r.height}` : ''}  ${e.ref}`
        })
        return `${body.join('\n')}${v?.hint ? `\n${v.hint}` : ''}`
      }
    ),
    tool(
      'info',
      'Describe one element by ref: role, name, description, value, states, actions, attributes, geometry and parent chain. Read-only.',
      { ref: { ...REF, description: 'Element reference.' }, selector: SELECTOR },
      'info',
      (a) => ({ ref: a.ref, selector: a.selector }),
      (v) => asJson(v)
    ),
    tool(
      'click',
      'Click an element (by ref or selector) �?runs its accessibility click/activate/toggle action when available, otherwise moves the real pointer to the element centre and clicks (xdotool on X11, kdotool on Wayland). Modifies the application.',
      {
        ref: REF,
        selector: SELECTOR,
        button: { type: 'string', enum: ['left', 'middle', 'right'], description: 'Mouse button (pointer path only).' },
        clicks: { type: 'integer', description: 'Click count, 2 = double click (default 1).' },
        strategy: { type: 'string', enum: ['auto', 'atspi', 'xdotool', 'kdotool'], description: 'Force one input backend (default auto).' },
        dry_run: { type: 'boolean', description: 'Resolve the target and report the click point without clicking.' }
      },
      'click',
      (a) => ({ ref: a.ref, selector: a.selector, button: a.button, clicks: a.clicks, strategy: a.strategy, dry_run: a.dry_run === true }),
      (v) => `clicked ${v?.x},${v?.y} (${v?.button ?? 'left'} x${v?.clicks ?? 1}) via ${v?.backend ?? '?'}${v?.dryRun ? ' [dry run]' : ''} �?ref ${v?.ref ?? ''}`,
      { mutating: true }
    ),
    tool(
      'keys',
      'Press a key or key combination in the focused window, e.g. "ctrl+l", "Enter", "ALT+F4", "ctrl+shift+t". Modifies the application.',
      {
        key: { type: 'string', required: true, description: 'Combination: modifiers + final key (ctrl/shift/alt/super), or a single key name.' },
        repeat: { type: 'integer', description: 'Repeat count (default 1).' }
      },
      'press',
      (a) => ({ key: a.key, repeat: a.repeat }),
      (v) => `pressed ${v?.combo} x${v?.repeat ?? 1} via ${v?.backend ?? '?'}`,
      { mutating: true }
    ),
    tool(
      'type',
      'Type text into the focused widget (ref optional: focuses it first). Uses the accessibility editable-text interface when available, else xdotool/kdotool synthetic typing. Modifies the application.',
      {
        text: { type: 'string', required: true, description: 'Text to type.' },
        ref: { ...REF, description: 'Optional field to focus and type into.' },
        submit: { type: 'boolean', description: 'Press Return afterwards.' },
        interval_ms: { type: 'integer', description: 'Delay between keys in ms (default 0).' },
        dry_run: { type: 'boolean', description: 'Report what would be typed.' }
      },
      'type',
      (a) => ({ text: a.text, ref: a.ref, submit: a.submit === true, interval_ms: a.interval_ms, dry_run: a.dry_run === true }),
      (v) => `typed ${JSON.stringify(v?.text ?? '')} via ${v?.backend ?? '?'}${v?.submit ? ' + Return' : ''}${v?.dryRun ? ' [dry run]' : ''}`,
      { mutating: true }
    ),
    tool(
      'set_value',
      'Set an element value through its accessibility Value/editable-text interface (text fields, sliders, spin boxes). Falls back with a clear error when the widget exposes neither. Modifies the application.',
      { ref: REF, selector: SELECTOR, value: { type: 'string', required: true, description: 'New value (numbers are applied through the Value interface).' } },
      'set',
      (a) => ({ ref: a.ref, selector: a.selector, value: a.value }),
      (v) => `set ${v?.interface} to ${JSON.stringify(v?.value ?? '')} (ref ${v?.ref ?? ''})`,
      { mutating: true }
    ),
    tool(
      'scroll',
      'Scroll with the wheel over an element or at explicit x/y coordinates. Modifies the application.',
      {
        ref: REF,
        selector: SELECTOR,
        direction: { type: 'string', enum: ['up', 'down', 'left', 'right'], description: 'Wheel direction (default down).' },
        amount: { type: 'integer', description: 'Wheel clicks (default 3).' },
        x: { type: 'integer', description: 'Point x (instead of an element).' },
        y: { type: 'integer', description: 'Point y.' }
      },
      'scroll',
      (a) => ({ ref: a.ref, selector: a.selector, x: a.x, y: a.y, direction: a.direction, amount: a.amount }),
      (v) => `scrolled ${v?.direction} x${v?.amount} at ${v?.x},${v?.y} via ${v?.backend ?? '?'}`,
      { mutating: true }
    ),
    tool(
      'wait_for',
      'Poll until a condition is met: an element appears, a window appears or closes, or the desktop gets keyboard focus. Returns the match, or a timeout error carrying the last observed state. Read-only.',
      {
        target: { type: 'string', enum: ['element', 'window', 'window_gone'], description: 'What to wait for (default element).' },
        selector: SELECTOR,
        ref: { ...REF, description: 'Wait for this ref to disappear (target "gone").' },
        timeout_s: { type: 'number', description: 'Timeout in seconds (default 10).' },
        interval_s: { type: 'number', description: 'Poll interval in seconds (default 0.25).' }
      },
      'wait',
      (a) => ({
        for: a.target === 'window' ? 'window' : a.target === 'window_gone' ? 'window-gone' : a.ref ? 'gone' : 'element',
        ref: a.ref,
        selector: a.selector,
        window: a.selector?.window,
        app: a.selector?.app,
        timeout: a.timeout_s,
        interval: a.interval_s
      }),
      (v) => `met after ${v?.elapsed ?? '?'}s: ${asJson(v?.element ?? v?.window ?? v?.gone ?? v)}`,
      { mutating: false }
    ),
    tool(
      'screenshot',
      'Capture the desktop, one window or one element as PNG and return the file path. Read-only (pixels are saved to /tmp on the Linux side).',
      {
        window: { type: 'string', description: 'Window title (substring).' },
        app: { type: 'string', description: 'Application name.' },
        ref: REF,
        output: { type: 'string', description: 'Absolute path inside Linux for the PNG (default /tmp/kde-uia-*.png).' },
        strategy: { type: 'string', enum: ['auto', 'kwin', 'spectacle', 'grim', 'import', 'xwd', 'portal'], description: 'Capture backend (default auto).' }
      },
      'screenshot',
      (a) => ({ window: a.window, app: a.app, ref: a.ref, output: a.output, strategy: a.strategy }),
      (v) => `saved ${v?.path} (${v?.width}x${v?.height}, ${v?.strategy}, scale ${v?.scale ?? 1})`
    ),
    tool(
      'activate',
      'Activate (raise and focus) a window, or close/minimize/maximize/move/resize it. Uses KWin scripting (Wayland and X11) or xdotool/wmctrl on X11. Modifies the desktop.',
      {
        action: { type: 'string', enum: ['activate', 'close', 'minimize', 'maximize', 'restore', 'move', 'resize'], description: 'What to do (default activate).' },
        window: { type: 'string', description: 'Window title (substring).' },
        app: { type: 'string', description: 'Application name.' },
        id: { type: 'string', description: 'Window id from kde_uia_windows (most exact).' },
        x: { type: 'integer', description: 'move: x coordinate.' },
        y: { type: 'integer', description: 'move: y coordinate.' },
        width: { type: 'integer', description: 'resize: width.' },
        height: { type: 'integer', description: 'resize: height.' }
      },
      'window-op',
      (a) => ({ action: a.action ?? 'activate', window: a.window, app: a.app, id: a.id, x: a.x, y: a.y, width: a.width, height: a.height }),
      (v) => `${v?.op ?? 'activate'} ok (${v?.source ?? 'wm'}) ${asJson(v?.window ?? {})}`,
      { mutating: true }
    )
  ]
  return tools.filter((entry) => entry !== null)
}

/** Names of tools that change desktop state. */
export const MUTATING_TOOLS = new Set([
  'kde_uia_click',
  'kde_uia_keys',
  'kde_uia_type',
  'kde_uia_set_value',
  'kde_uia_scroll',
  'kde_uia_activate'
])
