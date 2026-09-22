package main

import (
	"os"
	"strconv"
	"sync"
	"time"

	"github.com/sirupsen/logrus"
)

// 账号护栏。
//
// 背景：MCP 的每个业务接口底层都会真的拉起一个浏览器去访问 xiaohongshu.com。
// 调用方若以秒级轮询渠道状态，一小时就是几百次真实访问，在平台侧等同机器人行为。
// 这里加两件事，不改变业务语义，只加护栏：
//  1. browserBudget：真实浏览器会话的滑动窗口计数，超限由中间件直接拒绝（fail closed）；
//  2. statusCache：缓存 login/status，让轮询几乎不再产生浏览器。
//
// 环境变量：
//
//	XHS_BUDGET_MAX             窗口内允许的浏览器会话数，<=0 表示不限流（默认 30）
//	XHS_BUDGET_WINDOW_SECONDS  窗口长度（默认 600）
//	XHS_STATUS_TTL_SECONDS     login/status 缓存时长，<=0 表示不缓存（默认 300）
var (
	xhsBudget     = newBrowserBudget()
	loginStatusCA = newStatusCache()
)

func envInt(name string, def int) int {
	raw := os.Getenv(name)
	if raw == "" {
		return def
	}
	v, err := strconv.Atoi(raw)
	if err != nil {
		logrus.Warnf("环境变量 %s=%q 不是整数，用默认值 %d", name, raw, def)
		return def
	}
	return v
}

// browserBudget 统计滑动窗口内真实拉起过多少次浏览器会话。
type browserBudget struct {
	mu     sync.Mutex
	marks  []time.Time // 每次会话的时间戳，仅保留窗口内的
	max    int         // <=0 表示不限流
	window time.Duration
}

func newBrowserBudget() *browserBudget {
	return &browserBudget{
		max:    envInt("XHS_BUDGET_MAX", 30),
		window: time.Duration(envInt("XHS_BUDGET_WINDOW_SECONDS", 600)) * time.Second,
	}
}

// Record 记一次真实浏览器会话；max<=0 时不计数。
func (b *browserBudget) Record() {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.max <= 0 {
		return
	}
	now := time.Now()
	b.trimLocked(now)
	b.marks = append(b.marks, now)
}

// Snapshot 返回窗口内已用会话数、上限、窗口长度。max<=0 时已用数恒为 0。
func (b *browserBudget) Snapshot() (used, max int, window time.Duration) {
	b.mu.Lock()
	defer b.mu.Unlock()

	if b.max <= 0 {
		return 0, 0, b.window
	}
	b.trimLocked(time.Now())
	return len(b.marks), b.max, b.window
}

// Exhausted 窗口内会话数是否已达上限。
func (b *browserBudget) Exhausted() bool {
	used, max, _ := b.Snapshot()
	return max > 0 && used >= max
}

// trimLocked 丢弃窗口外的时间戳。调用方必须已持锁。
func (b *browserBudget) trimLocked(now time.Time) {
	cut := now.Add(-b.window)
	i := 0
	for i < len(b.marks) && b.marks[i].Before(cut) {
		i++
	}
	if i > 0 {
		b.marks = append(b.marks[:0], b.marks[i:]...)
	}
}

// flight 表示一次正在进行的探测。并发调用等它的结果，而不是各自再开一个浏览器。
type flight struct {
	done chan struct{}
	resp *LoginStatusResponse
	err  error
}

// statusCache 缓存 login/status 的结果。
// 探测登录态要开一次浏览器，而它恰恰是被轮询最多的接口。
type statusCache struct {
	mu   sync.Mutex
	at   time.Time
	resp *LoginStatusResponse
	ttl  time.Duration
	f    *flight // 非 nil = 有一次探测正在跑
}

func newStatusCache() *statusCache {
	// 默认 300s 而不是 60s：TTL 直接决定「上方轮询多密，都最多每分钟开几个浏览器」。
	// 60s 时实测仍有约 60 次/小时的真实访问，对手上有风控标记的账号还是太多。
	// 交互流程不受影响——登录成功与删除 cookies 都会主动 invalidate。
	return &statusCache{ttl: time.Duration(envInt("XHS_STATUS_TTL_SECONDS", 300)) * time.Second}
}

// get 命中未过期缓存时返回副本，避免调用方改到缓存本体。
func (c *statusCache) get() (*LoginStatusResponse, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.resp == nil || c.ttl <= 0 || time.Since(c.at) > c.ttl {
		return nil, false
	}
	cp := *c.resp
	return &cp, true
}

func (c *statusCache) set(r *LoginStatusResponse) {
	if r == nil {
		return
	}
	c.mu.Lock()
	defer c.mu.Unlock()

	cp := *r
	c.resp = &cp
	c.at = time.Now()
}

// peek 返回缓存的登录态（**不管是否过期**）以及它的年龄。
// 轮询路径用它做到「只报告上次结果，不主动开浏览器」。
func (c *statusCache) peek() (resp *LoginStatusResponse, age time.Duration, ok bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.resp == nil {
		return nil, 0, false
	}
	cp := *c.resp
	return &cp, time.Since(c.at), true
}

// invalidate 登录态发生变化后必须调用，否则最长要等一个 TTL 才看得到真实状态。
func (c *statusCache) invalidate() {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.resp = nil
	c.at = time.Time{}
}

// begin 是「缓存 + 单飞」的入口，用来挡缓存击穿。
//
// 为什么必须有：TTL 到期的那一瞬间，同一秒到达的两个请求会**双双未命中**，
// 于是各开一个浏览器 —— 用户看到小红书窗口成对弹出。
// 实测后端有两条独立路径以 60 秒为周期同时打过来（/api/platforms 与 /api/env），
// 所以这不是理论风险。
//
// 返回：
//
//	cached 非 nil           -> 缓存命中，直接用
//	mine=false, wait 非 nil -> 已有探测在跑，等 wait.done 后复用它的结果
//	mine=true, wait 非 nil  -> 由本次调用去探测，结束后必须调 end
func (c *statusCache) begin() (cached *LoginStatusResponse, wait *flight, mine bool) {
	c.mu.Lock()
	defer c.mu.Unlock()

	if c.resp != nil && c.ttl > 0 && time.Since(c.at) <= c.ttl {
		cp := *c.resp
		return &cp, nil, false
	}
	if c.f != nil {
		return nil, c.f, false
	}
	c.f = &flight{done: make(chan struct{})}
	return nil, c.f, true
}

// end 结束一次探测：成功则回填缓存，并唤醒所有等待者。
func (c *statusCache) end(f *flight, resp *LoginStatusResponse, err error) {
	c.mu.Lock()
	if resp != nil {
		cp := *resp
		c.resp = &cp
		c.at = time.Now()
	}
	f.resp, f.err = resp, err
	c.f = nil
	c.mu.Unlock()

	close(f.done)
}
