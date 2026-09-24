-- GCRA rate limiter (docs/34_RATE_LIMITING.md §1)
-- KEYS[1] = key ; ARGV = now_ms, emission_interval_ms, burst, cost
-- returns {allowed, retry_after_s, remaining, reset_s}
local now = tonumber(ARGV[1])
local T = tonumber(ARGV[2])
local burst = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local tat = tonumber(redis.call("GET", KEYS[1]) or ARGV[1])
tat = math.max(tat, now)
local new_tat = tat + T * cost
local allow_at = new_tat - burst * T
if allow_at > now then
  return {0, math.ceil((allow_at - now) / 1000), 0, math.ceil((tat - now) / 1000)}
end
redis.call("SET", KEYS[1], tostring(new_tat), "PX", math.ceil(new_tat - now) + 1000)
return {1, 0, math.floor((now - allow_at) / T), math.ceil((new_tat - now) / 1000)}
