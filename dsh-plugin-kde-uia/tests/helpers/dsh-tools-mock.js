/**
 * Minimal stand-in for `defineTool` when the real package is unavailable.
 * Enforces the documented author-schema vocabulary (see
 * `@deepseek-ai/dsh-tools` `src/schema.ts`):
 *
 * - every node allows `description`, `title`, `default`, `examples`;
 * - every node carries its own `type` (or `oneOf` with >= 2 branches, no `type`);
 * - property nodes additionally allow `required: true`;
 * - `object` needs an explicit boolean `additionalProperties`;
 * - `array` may carry `items`;
 * - anything else is a schema the real compiler would reject.
 */
export function createCoreMockDefineTool() {
  const ANNOTATIONS = ['description', 'title', 'default', 'examples']
  const TYPES = ['string', 'number', 'integer', 'boolean', 'null', 'array', 'object', 'json']
  const fail = (message) => { throw new Error(`JsonSchemaError: ${message}`) }

  const compileValue = (input, path, allowRequired) => {
    if (!input || typeof input !== 'object' || Array.isArray(input)) fail(`${path} must be a value schema object`)
    const node = {}
    let type
    if (Object.hasOwn(input, 'oneOf')) {
      for (const key of Object.keys(input)) {
        if (![...ANNOTATIONS, 'oneOf', ...(allowRequired ? ['required'] : [])].includes(key)) fail(`${path}.${key} is not supported by the value schema DSL`)
      }
      if (Object.hasOwn(input, 'type')) fail(`${path} cannot declare both type and oneOf`)
      if (!Array.isArray(input.oneOf) || input.oneOf.length < 2) fail(`${path}.oneOf must be an array of at least two value schemas`)
      node.oneOf = input.oneOf.map((branch, index) => compileValue(branch, `${path}.oneOf[${index}]`, false))
    } else {
      type = input.type
      if (!TYPES.includes(type)) fail(`${path}.type must be string/number/integer/boolean/null/array/object/json, or use oneOf`)
      for (const key of Object.keys(input)) {
        if (![...ANNOTATIONS, 'type', 'enum', 'const', ...(allowRequired ? ['required'] : []), ...(type === 'array' ? ['items'] : []), ...(type === 'object' ? ['properties', 'additionalProperties'] : [])].includes(key)) {
          fail(`${path}.${key} is not supported by the value schema DSL`)
        }
      }
      // `json` compiles to an annotation-only schema: no `type` in the output.
      if (type !== 'json') node.type = type
      if (Object.hasOwn(input, 'enum')) {
        if (!Array.isArray(input.enum) || input.enum.length === 0) fail(`${path}.enum must be a non-empty array of scalar values`)
        node.enum = [...input.enum]
      }
      if (Object.hasOwn(input, 'const')) node.const = input.const
      if (type === 'array' && Object.hasOwn(input, 'items')) node.items = compileValue(input.items, `${path}.items`, false)
      if (type === 'object') {
        if (typeof input.additionalProperties !== 'boolean') fail(`${path}.additionalProperties must be explicitly true or false`)
        node.additionalProperties = input.additionalProperties
        if (input.properties) {
          node.properties = {}
          for (const [key, spec] of Object.entries(input.properties)) {
            node.properties[key] = compileValue(spec, `${path}.properties.${key}`, true)
          }
        }
      }
    }
    for (const key of ANNOTATIONS) if (Object.hasOwn(input, key)) node[key] = input[key]
    return node
  }

  const compileParameters = (spec) => {
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) fail('parameters must be an object of value schemas')
    const properties = {}
    const required = []
    for (const [key, value] of Object.entries(spec)) {
      if (value && Object.hasOwn(value, 'required') && value.required !== true) fail(`parameters.${key}.required must be true when present`)
      properties[key] = compileValue(value, `parameters.${key}`, true)
      if (value?.required === true) required.push(key)
    }
    return { type: 'object', properties, ...(required.length ? { required } : {}) }
  }

  return (options) => {
    if (!options || typeof options.name !== 'string') fail('defineTool needs a name')
    return {
      name: options.name,
      description: options.description,
      parameters: compileParameters(options.parameters ?? {}),
      output: {
        schema: compileValue(options.output?.schema ?? {}, 'schema', false),
        render: options.output?.render ?? (() => [])
      },
      execute: options.execute,
      presentCall: options.presentCall,
      isConcurrencySafe: options.isConcurrencySafe,
      timeoutMs: options.timeoutMs,
      deferLoading: options.deferLoading
    }
  }
}
