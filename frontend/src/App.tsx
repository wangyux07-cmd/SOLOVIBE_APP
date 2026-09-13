import { useState, useRef, useEffect } from "react";
import {
  motion,
  AnimatePresence
} from "motion/react";
import { apiUrl } from './api';
import {
  Compass,
  Map as MapIcon,
  MessageSquare,
  User,
  Clock,
  CreditCard,
  MapPin,
  Star,
  Check,
  Sparkles,
  MoreHorizontal,
  PlusCircle,
  Mic,
  ArrowUp,
  ArrowLeft,
  ArrowRight,
  Zap,
  Calendar,
  RefreshCw,
  Sliders,
  Cpu,
  ThumbsUp,
  Store,
  Navigation,
  Filter,
  Smile,
  TrendingUp,
  Award,
  BookOpen,
  Send,
  Heart,
  Activity,
  UserCheck,
  ShieldAlert,
  HelpCircle,
  Footprints,
  Play
} from "lucide-react";

import {
  ScreenId,
  Message,
  WanderPlan
} from "./types";

import {
  ASSETS,
  INITIAL_WANDER_PLANS,
  MOCK_LEADERBOARD,
  COMMUNITY_LINES,
  MAP_PINS,
  RECOMMENDED_PLACES,
  RIVERSIDE_EVAL_DIMENSIONS,
  ROUTE_MERCHANTS
} from "./data";

export default function App() {
  console.log("App component is starting to render");
  // Mobile chassis navigation state
  const [currentScreen, setCurrentScreen] = useState<ScreenId>("chat");
  const [selectedMerchantId, setSelectedMerchantId] = useState<string>("line-1");

  // HashRouter state synchronization
  useEffect(() => {
    const handleHashChange = () => {
      const hash = window.location.hash.replace("#", "");
      if (
        hash === "chat" ||
        hash === "solutions" ||
        hash === "booking" ||
        hash === "challenge" ||
        hash === "map" ||
        hash === "resonance" ||
        hash === "index"
      ) {
        setCurrentScreen(hash as ScreenId);
      } else if (!hash) {
        window.location.hash = "chat";
      }
    };

    // Run on initial mount
    handleHashChange();

    window.addEventListener("hashchange", handleHashChange);
    return () => {
      window.removeEventListener("hashchange", handleHashChange);
    };
  }, []);

  useEffect(() => {
    if (window.location.hash.replace("#", "") !== currentScreen) {
      window.location.hash = currentScreen;
    }
  }, [currentScreen]);
  const [prevScreens, setPrevScreens] = useState<ScreenId[]>([]);
  const [challengeTab, setChallengeTab] = useState<"task" | "pk">("task");
  const [selectedWanderMood, setSelectedWanderMood] = useState<string>("轻松放空");

  // User Exploration Stats
  const [score, setScore] = useState(0);
  const [completedQuests, setCompletedQuests] = useState(0);
  const [isChallengeAccepted, setIsChallengeAccepted] = useState(false);
  const [isChallengeCompleted, setIsChallengeCompleted] = useState(false);
  const [hasCheckedInToday, setHasCheckedInToday] = useState(false);

  // Chat/AI History States
  const [currentThreadId, setCurrentThreadId] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<Message[]>([
    {
      id: "msg-1",
      role: "model",
      content: "嗨，周末好呀 👋 我是你的城市漫步伙伴 Solo。今天外面的阳光很不错，感觉心情怎么样？或者有什么特别想去的地方吗？",
      timestamp: "今天 10:42 AM"
    }
  ]);
  const [inputText, setInputText] = useState("");
  const [isAiTyping, setIsAiTyping] = useState(false);
  
  // Custom chat message to supplement AI generator inputs
  const [isChatSubmitted, setIsChatSubmitted] = useState(false);

  // Solutions screen states
  const [selectedPlanId, setSelectedPlanId] = useState<string>("plan-a");
  const [wanderPlans, setWanderPlans] = useState<WanderPlan[]>(INITIAL_WANDER_PLANS);

  // Booking Execution States
  const [bookingProgress, setBookingProgress] = useState(3); // 0 to 3 stages checked
  const [isBookingConfirmed, setIsBookingConfirmed] = useState(false);

  // PK Challenger States
  const [isCompletedPK, setIsCompletedPK] = useState(false);
  const [anonymousPK, setAnonymousPK] = useState(false);
  const [pkParticipants, setPkParticipants] = useState(MOCK_LEADERBOARD);
  const [pkTotalCompleted, setPkTotalCompleted] = useState(856);

  // Community / Resonance States
  const [resonanceCount, setResonanceCount] = useState(238);
  const [resonanceNearby, setResonanceNearby] = useState(17);
  const [departedSelf, setDepartedSelf] = useState(false);
  const [likedCount, setLikedCount] = useState(157);
  const [floatingHearts, setFloatingHearts] = useState<{ id: number; left: number }[]>([]);

  // Map Navigation States
  const [mapCenterMsg, setMapCenterMsg] = useState("上海 城市探索中");
  const [recalculatingMap, setRecalculatingMap] = useState(false);

  // Chat container reference for scroll
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // Tracking navigation stack for "Back" button
  const pushScreen = (screen: ScreenId) => {
    setPrevScreens((prev) => [...prev, currentScreen]);
    setCurrentScreen(screen);
  };

  const popScreen = () => {
    if (prevScreens.length > 0) {
      const nextStack = [...prevScreens];
      const prev = nextStack.pop();
      setPrevScreens(nextStack);
      if (prev) setCurrentScreen(prev);
    } else {
      setCurrentScreen("challenge");
    }
  };

  // Scroll to bottom of chat
  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [chatMessages, isAiTyping]);

  // Handle chat submission to server-side Gemini API (or robust fallback)
  const handleSendMessage = async (customPrompt?: string) => {
    const promptToSend = customPrompt || inputText;
    if (!promptToSend.trim()) return;

    const userMsg: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: promptToSend,
      timestamp: new Date().toLocaleTimeString("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: true
      })
    };

    setChatMessages((prev) => [...prev, userMsg]);
    setInputText("");
    setIsChatSubmitted(customPrompt ? true : isChatSubmitted);
    setIsAiTyping(true);

    try {
      const chatPayload = [...chatMessages, userMsg].map((msg) => ({
        role: msg.role,
        content: msg.content
      }));

      // Protocol v2.0 - 遵循新API规范
      const requestBody = {
        message: userMsg.content, // 新协议要求单个message字段
        ...(currentThreadId && { thread_id: currentThreadId }) // body中传递thread_id
      };
      
      const res = await fetch(apiUrl('/api/chat'), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody)
      });

      const data = await res.json();
      if (!res.ok) throw new Error(data.error?.message || `请求失败（HTTP ${res.status}）`);
      
      // Protocol v2.0 - 处理新返回格式
      // 始终使用返回的thread_id确保连续性
      if (data.thread_id) {
        setCurrentThreadId(data.thread_id);
        console.log(`[Protocol-v2] Thread ID 更新: ${data.thread_id}`);
      }
      
      // 新state_info日志（用于调试）
      if (data.state_info) {
        console.log(`[Protocol-v2] 状态信息:`, data.state_info);
        
        // 根据state决定是否显示位置提示
        if (data.state_info.has_location) {
          console.log("✅ 地址已设置");
        } else if (data.state_info.needs_user_input) {
          console.log("📍 需要用户提供地址");
        }
      }
      
      const modelMsg: Message = {
        id: `msg-${Date.now() + 1}`,
        role: "model",
        content: data.response || "服务没有返回回复，请稍后重试。",
        timestamp: new Date().toLocaleTimeString("zh-CN", {
          hour: "2-digit",
          minute: "2-digit",
          hour12: true
        })
      };

      setChatMessages((prev) => [...prev, modelMsg]);
    } catch (e) {
      console.error("Failed to communicate with API:", e);
      // Fallback
      setTimeout(() => {
        const fallbackMsg: Message = {
          id: `msg-${Date.now() + 1}`,
          role: "model",
          content: e instanceof Error ? e.message : "连接失败，请检查服务后重试。",
          timestamp: new Date().toLocaleTimeString("zh-CN", {
            hour: "2-digit",
            minute: "2-digit"
          })
        };
        setChatMessages((prev) => [...prev, fallbackMsg]);
      }, 1500);
    } finally {
      setIsAiTyping(false);
    }
  };

  // Quick Action Trigger Generator
  const triggerAutoPlanGeneration = () => {
    pushScreen("solutions");
  };

  // Trigger floating heart animations
  const handleLikeInteractions = () => {
    setLikedCount((prev) => prev + 1);
    const newHeartId = Date.now();
    const randomLeft = Math.floor(Math.random() * 80) + 10; // 10% to 90%
    setFloatingHearts((prev) => [...prev, { id: newHeartId, left: randomLeft }]);
    setTimeout(() => {
      setFloatingHearts((prev) => prev.filter((h) => h.id !== newHeartId));
    }, 2000);
  };

  // Swap target challenges
  const swapDailyTask = () => {
    const defaultPlan = wanderPlans[0];
    const randomizedPlans = [
      ...wanderPlans.slice(1),
      {
        ...defaultPlan,
        title: "去一处少人的城市滨水步道慢走 45 分钟",
        quote: "“听着水浪拍岸的声音，呼吸潮湿清爽的空气，非常适合理清思路。”",
        duration: "45min"
      }
    ];
    setWanderPlans(randomizedPlans);
    // Visual trigger cue
    alert("✨ AI 已为您重新匹配合适的一人漫游路线和任务！");
  };

  // Complete PK with CheckIn Action
  const handlePKCheckIn = () => {
    setIsCompletedPK(true);
    setPkTotalCompleted((prev) => prev + 1);
    setScore((prev) => prev + 50); // Explorer progress add
    setCompletedQuests((prev) => prev + 1);
    // Change self rank on leaderboard on check-in
    setPkParticipants((prev) =>
      prev.map((p) =>
        p.isSelf ? { ...p, timeSpent: "已完成 ✔️", rating: 4.9, rank: 9 } : p
      )
    );
    setHasCheckedInToday(true);
    alert("🎉 恭喜完成今日一人挑战！探索值已增加，您今天的漫游勋章已点亮！");
    pushScreen("map");
  };

  // AI Booking automatic intervals to simulate scheduling live desk
  const triggerAIProgressUpdates = () => {
    setBookingProgress(0);
    const intervalIds = [1, 2, 3].map((stage, idx) => {
      return setTimeout(() => {
        setBookingProgress(stage);
      }, (idx + 1) * 1500);
    });
    return () => intervalIds.forEach((id) => clearTimeout(id));
  };

  const handleBookNow = () => {
    setIsChallengeAccepted(true);
    triggerAIProgressUpdates();
    pushScreen("booking");
  };

  return (
    <div className="flex flex-col lg:flex-row min-h-screen bg-neutral-900 text-neutral-100 font-sans selection:bg-amber-300 selection:text-neutral-900 antialiased overflow-x-hidden">
      
      {/* LEFT HEADER / INFO BOARD: Interactive Simulator Controller */}
      <div className="flex-1 p-6 md:p-12 lg:max-w-md flex flex-col justify-between border-b lg:border-b-0 lg:border-r border-neutral-800 bg-neutral-950/40 backdrop-blur-3xl z-10">
        <div>
          <div className="flex items-center gap-2 mb-4">
            <span className="p-2 rounded-full bg-amber-500/10 text-amber-400">
              <Sparkles className="w-5 h-5" />
            </span>
            <span className="text-xs font-mono tracking-widest uppercase text-neutral-400">
              Interactive Design System
            </span>
          </div>
          
          <h1 className="text-3xl md:text-4xl font-extrabold tracking-tight text-white mb-2 font-display-lg leading-tight">
            SoloVibe
          </h1>
          <p className="text-amber-400 font-bold mb-4 tracking-wide text-sm">
            AI Companion &amp; Guide to Empowered Solitude
          </p>
          <p className="text-xs text-neutral-400 leading-relaxed mb-8">
            这是一个为了鼓励在城市里的年轻人享受“高质量独处”而设计的产品细节探索器。
            它将“一个人行动”重塑为带有游戏色彩的“城市副本探索”和“轻量PK”，通过温暖、疗愈的AI助理来减少社交内耗与选择纠结。
          </p>

          {/* SCREEN TOGGLER: Developer Fast Checkin */}
          <div className="space-y-3 mb-8">
            <h3 className="text-xs font-mono font-bold tracking-widest uppercase text-amber-500 mb-2">
              展示演示流程 (7 大线性循序界面) :
            </h3>
            
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <button
                onClick={() => {
                  setCurrentScreen("chat");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 ${
                  currentScreen === "chat"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <MessageSquare className="w-3.5 h-3.5 shrink-0" />
                AI单人对话
              </button>

              <button
                onClick={() => {
                  setCurrentScreen("solutions");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 ${
                  currentScreen === "solutions"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <Sliders className="w-3.5 h-3.5 shrink-0" />
                3个定制方案
              </button>

              <button
                onClick={() => {
                  setCurrentScreen("booking");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 ${
                  currentScreen === "booking"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <PlusCircle className="w-3.5 h-3.5 shrink-0" />
                AI正在安排
              </button>

              <button
                onClick={() => {
                  setCurrentScreen("challenge");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 ${
                  currentScreen === "challenge"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <Award className="w-3.5 h-3.5 shrink-0" />
                今日出门挑战
              </button>

              <button
                onClick={() => {
                  setCurrentScreen("map");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 ${
                  currentScreen === "map"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <MapIcon className="w-3.5 h-3.5 shrink-0" />
                你的城市副本
              </button>

              <button
                onClick={() => {
                  setCurrentScreen("resonance");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 ${
                  currentScreen === "resonance"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <Smile className="w-3.5 h-3.5 shrink-0" />
                发现同路人
              </button>

              <button
                onClick={() => {
                  setCurrentScreen("index");
                  setPrevScreens([]);
                }}
                className={`py-2 px-2.5 rounded-lg text-left transition-all flex items-center gap-1.5 col-span-2 ${
                  currentScreen === "index"
                    ? "bg-amber-400 text-neutral-950 font-bold shadow-md"
                    : "bg-neutral-900 hover:bg-neutral-800 text-neutral-300"
                }`}
              >
                <BookOpen className="w-3.5 h-3.5 shrink-0" />
                一人友好指数评估 (底层数据支撑)
              </button>
            </div>
          </div>
        </div>

        {/* METADATA SUMMARY & BRAND CODE */}
        <div className="mt-8 pt-6 border-t border-neutral-800">
          <div className="flex items-center gap-4 text-xs text-neutral-400 font-mono">
            <div>
              <p className="text-[10px] text-neutral-500 uppercase tracking-widest">Active City</p>
              <p className="font-semibold text-neutral-200">上海 / SHANGHAI</p>
            </div>
            <div>
              <p className="text-[10px] text-neutral-500 uppercase tracking-widest">Explorer Lvl</p>
              <p className="font-semibold text-neutral-200">街角漫游者 (Lvl 3)</p>
            </div>
          </div>
          
          <div className="mt-4 flex flex-wrap gap-2">
            <span className="px-2 py-0.5 rounded text-[10px] bg-neutral-800 text-neutral-300 border border-neutral-700">
              #PingFang SC
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] bg-neutral-800 text-neutral-300 border border-neutral-700">
              #Plus Jakarta Sans
            </span>
            <span className="px-2 py-0.5 rounded text-[10px] bg-amber-400/10 text-amber-400 border border-amber-400/20">
              #Gemini Flash-Enabled
            </span>
          </div>
        </div>
      </div>

      {/* CORE MOBILE SIMULATION CONTAINER */}
      <div className="flex-1 flex items-center justify-center p-4 bg-neutral-950 select-none relative">
        
        {/* Decorative Grid Accents */}
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#1f1f1f_1px,transparent_1px),linear-gradient(to_bottom,#1f1f1f_1px,transparent_1px)] bg-[size:4rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_50%,#000_70%,transparent_100%)] opacity-30 pointer-events-none"></div>
        
        {/* Device frame shadow glow */}
        <div className="absolute w-[390px] h-[800px] rounded-[48px] bg-amber-500/5 blur-[120px] pointer-events-none"></div>

        {/* PHYSICAL PHONE CHASSIS MODELLING */}
        <div 
          id="phone-frame"
          className="relative w-full max-w-[390px] h-[812px] rounded-[48px] border-[10px] border-neutral-800 bg-[#fcf9f8] text-neutral-900 shadow-[0_24px_60px_rgba(0,0,0,0.8)] overflow-hidden flex flex-col transition-colors duration-300"
          style={{ fontFamily: '"PingFang SC", "Plus Jakarta Sans", "Be Vietnam Pro", sans-serif' }}
        >
          {/* TOP STATUS BAR: Styled to iOS Dynamic Notch */}
          <div className="absolute top-0 left-0 w-full h-8 flex justify-between items-center px-6 z-[100] bg-transparent text-neutral-800 text-xs pointer-events-none select-none">
            <span className="font-semibold">SOLO VIBE</span>
            <div className="w-[110px] h-[22px] bg-neutral-900 rounded-full flex items-center justify-center pointer-events-auto shadow-sm">
              <div className="w-2.5 h-2.5 rounded-full bg-neutral-800 border-2 border-neutral-950 mr-1.5"></div>
              <div className="w-8 h-1 bg-neutral-800 rounded-full"></div>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="font-mono text-[11px] font-bold">10:42 AM</span>
              <div className="w-5 h-2.5 border border-neutral-800 rounded-sm p-0.5 flex items-center">
                <div className="h-full bg-neutral-800 w-[80%] rounded-xs"></div>
              </div>
            </div>
          </div>

          {/* COMMON HEADER COMPONENT (Matches Solo Headers in HTML templates) */}
          <header className="absolute top-8 left-0 w-full h-14 bg-[#fcf9f8]/85 backdrop-blur-xl border-b border-stone-200/40 flex justify-between items-center px-4 z-[90] shadow-sm select-none">
            {/* User Avatar Left */}
            <div 
              onClick={() => pushScreen("resonance")}
              className="w-8 h-8 rounded-full overflow-hidden border border-amber-300/60 shadow-xs cursor-pointer active:scale-95 transition-all"
            >
              <img 
                src={ASSETS.userProfile} 
                alt="User Profile" 
                className="w-full h-full object-cover"
                referrerPolicy="no-referrer"
              />
            </div>

            {/* Title middle with jump-back ability for testing nested screens */}
            <div className="text-center flex flex-col cursor-pointer" onClick={() => pushScreen("challenge")}>
              <h1 className="font-extrabold text-[20px] tracking-tighter text-amber-600 font-display-lg leading-tight select-none">
                SOLO
              </h1>
            </div>

            {/* Back Icon or More button right */}
            {prevScreens.length > 0 ? (
              <button 
                onClick={popScreen}
                className="w-8 h-8 flex items-center justify-center rounded-full bg-stone-100 hover:bg-stone-200 text-neutral-800 cursor-pointer transition-all active:scale-90"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            ) : (
              <button 
                onClick={() => pushScreen("index")}
                className="w-8 h-8 flex items-center justify-center rounded-full hover:bg-stone-100 text-[#4e4632] transition-colors cursor-pointer"
              >
                <MoreHorizontal className="w-5 h-5" />
              </button>
            )}
          </header>

          {/* INTERNAL CONTENT SWITCH BOARD */}
          <div className="flex-1 pt-22 pb-20 overflow-y-auto overflow-x-hidden hide-scrollbar scroll-smooth bg-[#fcf9f8]">
            <AnimatePresence mode="wait">
              <motion.div
                key={currentScreen}
                initial={{ opacity: 0, x: 15 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -15 }}
                transition={{ duration: 0.2 }}
                className="h-full w-full"
              >
                
                {/* 1. SCREEN: CHALLENGE (今日挑战合并版) */}
                {currentScreen === "challenge" && (
                  <div className="px-5 py-3 space-y-5">
                    {/* Header Title Block */}
                    <div>
                      <div className="text-[10px] font-mono font-bold tracking-widest text-[#725c00] bg-yellow-500/10 px-2.5 py-1 rounded inline-block mb-1.5 uppercase">
                        出门挑战 | 行动仪式与减压
                      </div>
                      <h2 className="text-2xl font-bold font-display-lg tracking-tight text-neutral-900 leading-tight">
                        今日出门挑战
                      </h2>
                      <p className="text-[#4e4632] text-xs font-body-md mt-1">
                        给你的出行一个温暖仪式感，完成微小的个人静躺或河畔观察 🌿
                      </p>
                    </div>

                    {/* Unified Combined Challenge & Progress Screen */}
                    <div className="space-y-5">
                      {/* 1. Sparkle advice block */}
                      <div className="p-3.5 bg-green-50/70 border border-green-200/40 rounded-xl flex items-center gap-3 shadow-xs">
                        <div className="p-1.5 rounded-full bg-green-100/80 text-green-600">
                          <Sparkles className="w-4 h-4 fill-green-600" />
                        </div>
                        <p className="text-xs text-green-900 leading-tight">
                          今天的挑战很有意思，点亮专属个人的河畔呼吸。✨
                        </p>
                      </div>

                      {/* 2. Active Challenge Card (sitting inside unvisited shop 30 min) */}
                      <div className="bg-white rounded-2xl overflow-hidden shadow-[0_4px_20px_rgba(0,0,0,0.03)] border border-stone-200/60 pb-5">
                        <div className="relative h-44 overflow-hidden">
                          <img 
                            src={wanderPlans[0].image} 
                            alt="Cafe" 
                            className="w-full h-full object-cover select-none"
                            referrerPolicy="no-referrer"
                          />
                          <div className="absolute top-4 left-4">
                            <span className="bg-[#725c00] text-white font-label-md text-[10px] uppercase font-bold px-2.5 py-1 rounded-full shadow-md">
                              今日限定
                            </span>
                          </div>
                          {/* Shading overlay */}
                          <div className="absolute inset-0 bg-gradient-to-t from-black/80 via-black/20 to-transparent flex flex-col justify-end p-4">
                            <h3 className="text-white text-lg font-bold font-display-lg tracking-tight drop-shadow-sm leading-snug">
                              {wanderPlans[0].title}
                            </h3>
                          </div>
                        </div>

                        {/* Four indicators */}
                        <div className="grid grid-cols-4 gap-2 px-4 py-4 text-center border-b border-stone-100 select-none">
                          <div className="flex flex-col items-center">
                            <Award className="w-4 h-4 text-amber-500 mb-1" />
                            <span className="text-[10px] text-stone-500">简单</span>
                          </div>
                          <div className="flex flex-col items-center">
                            <Clock className="w-4 h-4 text-[#725c00] mb-1" />
                            <span className="text-[10px] text-[#725c00] font-bold">专属时间</span>
                          </div>
                          <div className="flex flex-col items-center">
                            <CreditCard className="w-4 h-4 text-[#006c4f] mb-1" />
                            <span className="text-[10px] text-stone-500">低消费</span>
                          </div>
                          <div className="flex flex-col items-center">
                            <Navigation className="w-4 h-4 text-blue-500 mb-1" />
                            <span className="text-[10px] text-stone-500">1km 内</span>
                          </div>
                        </div>

                        {/* chips */}
                        <div className="flex flex-wrap gap-2 px-4 pt-4 shrink-0">
                          <span className="px-2.5 py-1 bg-stone-50 text-stone-600 rounded-full text-[10px] border border-stone-200/50">
                            低压力
                          </span>
                          <span className="px-2.5 py-1 bg-green-50 text-[#00694d] font-bold rounded-full text-[10px] border border-green-200/30">
                            一个人友好
                          </span>
                          <span className="px-2.5 py-1 bg-amber-50 text-[#725c00] rounded-full text-[10px] border border-amber-200/30">
                            附近可完成
                          </span>
                          
                          {/* Two visual chips grid */}
                          <div className="grid grid-cols-2 gap-3 text-xs w-full pt-2">
                            <div className="p-3 bg-stone-50 rounded-2xl border border-stone-200/40 text-center flex flex-col items-center gap-1 cursor-pointer active:scale-98">
                              <Award className="w-5 h-5 text-amber-500 animate-bounce" />
                              <span className="text-[10px] text-stone-600 line-clamp-1">点亮今日出门徽章</span>
                            </div>
                            <div className="p-3 bg-stone-50 rounded-2xl border border-stone-200/40 text-center flex flex-col items-center gap-1 cursor-pointer active:scale-98">
                              <MapIcon className="w-5 h-5 text-[#006c4f]" />
                              <span className="text-[10px] text-stone-600 line-clamp-1">解锁全新城市角落</span>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Quote box */}
                      <div className="p-4 bg-white border border-stone-100 italic text-[11px] leading-relaxed text-[#4e4632] rounded-2xl text-center shadow-xs">
                        “独自出发也是一种生活艺术。我们为你隐藏了无意义的嘈杂，只留下同行感，去试试看吧。”
                      </div>

                      {/* Personal Track timeline step cards */}
                      <div className="space-y-3">
                        <h4 className="text-[13px] font-extrabold text-neutral-800 flex items-center gap-1">
                          <Sliders className="w-4 h-4 text-amber-600" /> 漫步轨道进度
                        </h4>

                        <div className="bg-white/80 border border-stone-200/60 rounded-2xl p-4 shadow-xs">
                          {/* Step-by-step tracks with dynamic vertical connection line and micro-interactions */}
                          <div className="relative pl-1.5 space-y-4 font-medium">
                            {/* Vertical Connecting Line showing journey flow gradient */}
                            <div className="absolute left-[15px] top-2 bottom-3 w-[1.5px] bg-gradient-to-b from-green-550 via-amber-400 to-stone-200 rounded-full" />

                            {/* Step 1 */}
                            <div className="relative flex items-start gap-3.5 group transition-all duration-200 hover:translate-x-1 cursor-default">
                              <div className="relative z-10 w-4.5 h-4.5 rounded-full bg-green-100 text-green-700 font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5 shadow-xs transition-transform duration-200 group-hover:scale-110">
                                ✓
                              </div>
                              <div className="text-left">
                                <p className="text-xs font-bold text-stone-850 transition-colors group-hover:text-stone-950">1. 探索方案确认</p>
                                <p className="text-[10px] text-stone-400 transition-colors group-hover:text-stone-500">已成功为你预留河畔黄金座位并计入行程表</p>
                              </div>
                            </div>

                            {/* Step 2 */}
                            <div className="relative flex items-start gap-3.5 group transition-all duration-200 hover:translate-x-1 cursor-default">
                              <div className="relative z-10 w-4.5 h-4.5 rounded-full bg-green-100 text-green-700 font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5 shadow-xs transition-transform duration-200 group-hover:scale-110">
                                ✓
                              </div>
                              <div className="text-left">
                                <p className="text-xs font-bold text-stone-850 transition-colors group-hover:text-stone-950">2. 启程至漫游点</p>
                                <p className="text-[10px] text-stone-400 transition-colors group-hover:text-stone-500">大步跨出舒适圈，来到 1km 内的漫步目标目的地</p>
                              </div>
                            </div>

                            {/* Step 3 */}
                            <div className="relative flex items-start gap-3.5 group transition-all duration-200 hover:translate-x-1 cursor-default">
                              <div className="relative z-10 w-4.5 h-4.5 rounded-full bg-amber-100 text-[#725c00] font-bold text-[11px] flex items-center justify-center shrink-0 mt-0.5 animate-pulse shadow-xs transition-transform duration-200 group-hover:scale-110">
                                ⏳
                              </div>
                              <div className="text-left">
                                <p className="text-xs font-bold text-stone-855 transition-colors group-hover:text-stone-950 flex items-center gap-1.5">
                                  3. 个人静享专注
                                  <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-500 animate-ping" />
                                </p>
                                <p className="text-[10px] text-stone-500 transition-colors group-hover:text-stone-600">听歌、呼吸或观察，正享受专属你的沉浸时光</p>
                              </div>
                            </div>

                            {/* Step 4 */}
                            <div className="relative flex items-start gap-3.5 group transition-all duration-200 hover:translate-x-1 cursor-default">
                              <div className={`relative z-10 w-4.5 h-4.5 rounded-full font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5 shadow-xs transition-transform duration-200 group-hover:scale-110 ${hasCheckedInToday ? "bg-green-100 text-green-700" : "bg-stone-100 text-stone-400"}`}>
                                {hasCheckedInToday ? "✓" : "4"}
                              </div>
                              <div className="text-left">
                                <p className={`text-xs font-bold transition-colors group-hover:text-stone-900 ${hasCheckedInToday ? "text-[#00694d]" : "text-stone-400"}`}>4. 行程终章盖章</p>
                                <p className="text-[10px] text-stone-400 transition-colors group-hover:text-stone-550">点击下方确认打卡，解锁并收获今日的旅行勋章</p>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>

                      {/* Mood journaling selector segment */}
                      <div className="space-y-3">
                        <h4 className="text-[13px] font-extrabold text-neutral-800 flex items-center gap-1">
                          <Smile className="w-4 h-4 text-[#725c00]" /> 此时漫游心境
                        </h4>
                        
                        <p className="text-[10px] text-stone-500 -mt-1">
                          写下并记录你当前这段旅程的心境标签：
                        </p>

                        <div className="flex flex-wrap gap-2 select-none">
                          {[
                            { label: "🌿 轻松放空", value: "轻松放空" },
                            { label: "💭 触动灵感", value: "触动灵感" },
                            { label: "☕ 自在独享", value: "自在独享" },
                            { label: "🚶 漫无目的", value: "漫无目的" },
                            { label: "🎧 避风疗愈", value: "避风疗愈" }
                          ].map((mood) => {
                            const isSelected = selectedWanderMood === mood.value;
                            return (
                              <button
                                key={mood.value}
                                onClick={() => setSelectedWanderMood(mood.value)}
                                className={`px-3 py-1.5 rounded-full text-[11px] font-semibold transition-all duration-150 cursor-pointer border ${
                                  isSelected
                                    ? "bg-[#725c00] text-white border-transparent shadow-xs scale-102 font-bold"
                                    : "bg-stone-50 text-stone-600 border-stone-200/50 hover:bg-stone-100"
                                }`}
                              >
                                {mood.label}
                              </button>
                            );
                          })}
                        </div>
                      </div>

                      {/* Completion action bars */}
                      <div className="pt-2 space-y-2">
                        {!hasCheckedInToday ? (
                          <>
                            <button 
                              onClick={handlePKCheckIn}
                              className="w-full py-4 bg-amber-400 hover:bg-amber-300 font-bold text-neutral-900 text-[15px] rounded-full shadow-md flex items-center justify-center gap-2 cursor-pointer transition-transform active:scale-95 duration-100"
                            >
                              <Check className="w-4 h-4 text-neutral-900" />
                              记录漫游手记并打卡（生成我的城市副本）→
                            </button>

                            <button 
                              onClick={swapDailyTask}
                              className="w-full py-3.5 rounded-full border border-stone-850 hover:bg-stone-50 font-semibold text-neutral-800 text-sm cursor-pointer transition-all active:scale-95"
                            >
                              不喜欢，重新更换一个出行小挑战
                            </button>
                          </>
                        ) : (
                          <motion.div 
                            initial={{ opacity: 0, scale: 0.95 }}
                            animate={{ opacity: 1, scale: 1 }}
                            className="p-5 bg-gradient-to-br from-emerald-50 to-teal-50 border border-emerald-200 rounded-2xl text-center space-y-4 shadow-sm"
                          >
                            <div className="w-16 h-16 mx-auto bg-gradient-to-tr from-emerald-500 to-teal-400 text-white rounded-full flex items-center justify-center shadow-md animate-bounce">
                              <Award className="w-8 h-8 text-white fill-white/20" />
                            </div>
                            
                            <div className="space-y-1">
                              <p className="text-sm text-emerald-900 font-extrabold">🎉 挑战圆满达成！已收获漫步勋章</p>
                              <p className="text-[11px] text-emerald-700 leading-normal">
                                你今天的专属独处心境手记已由 AI 加密封存。探索值已记入这一座城市。
                              </p>
                            </div>

                            {/* Automation Guide Box */}
                            <div className="p-3 bg-white/80 border border-emerald-100 rounded-xl text-left flex gap-2.5 items-center">
                              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse shrink-0" />
                              <p className="text-[10px] text-emerald-800 leading-normal">
                                <strong>自动引导推荐：</strong>我们已把您今天的路线轨迹整理入了【城市副本】。点击下方看你在城市里留下的足迹吧！
                              </p>
                            </div>

                            <button
                              onClick={() => {
                                pushScreen("map");
                              }}
                              className="w-full py-3.5 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white font-bold text-xs rounded-full cursor-pointer transition-transform active:scale-95 duration-100 shadow-md flex items-center justify-center gap-1.5"
                            >
                              <MapIcon className="w-4 h-4" />
                              进入：城市副本 🗺️
                            </button>
                          </motion.div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* 2. SCREEN: AI CHAT (Solo 聊天) */}
                {currentScreen === "chat" && (
                  <div className="h-full flex flex-col justify-between">
                    
                    {/* New Core Step Indicator Header */}
                    <div className="px-4 py-2 bg-[#fdfaf8] border-b border-stone-200/40 shrink-0">
                      <div className="text-[10px] font-mono font-bold text-amber-600 bg-amber-500/10 px-2.5 py-1 rounded inline-block mb-1 tracking-wider uppercase">
                        AI 专属对话
                      </div>
                      <h3 className="text-xs font-bold text-neutral-800">
                        Solo 专属陪伴：倾听并洞察你此刻的想法 💭
                      </h3>
                    </div>

                    {/* Chat messages scrolling stream */}
                    <div className="flex-1 px-4 py-3 overflow-y-auto space-y-4 max-h-[410px]">
                      
                      {/* Solo context bubble memory trace */}
                      <div className="flex justify-center">
                        <div className="flex items-center gap-1.5 bg-yellow-100/60 text-[#6f5a00] border border-yellow-200/50 py-1.5 px-4 rounded-full text-[11px] max-w-[90%]">
                          <Cpu className="w-3.5 h-3.5" />
                          <span className="font-semibold text-center leading-none">
                            Solo 记得你上次喜欢安静的角落
                          </span>
                        </div>
                      </div>

                      {/* Today hour boundary */}
                      <div className="flex justify-center">
                        <span className="text-[9px] font-bold text-stone-400 py-0.5 px-2 bg-stone-100 rounded-full">
                          今天 10:42 AM
                        </span>
                      </div>

                      {/* Messages loop */}
                      {chatMessages.map((msg) => (
                        <div
                          key={msg.id}
                          className={`flex items-start gap-2.5 ${
                            msg.role === "user" ? "justify-end" : "justify-start"
                          }`}
                        >
                          {/* AI Avatar */}
                          {msg.role === "model" && (
                            <div className="w-7 h-7 rounded-full bg-yellow-100 flex items-center justify-center border border-yellow-400/20 shrink-0 shadow-xs">
                              <Sparkles className="w-3.5 h-3.5 text-amber-500" />
                            </div>
                          )}

                          {/* Message item */}
                          <div className="max-w-[80%] flex flex-col">
                            <div
                              className={`p-3.5 rounded-2xl text-xs leading-relaxed shadow-xs ${
                                msg.role === "user"
                                  ? "bg-amber-400 text-neutral-900 rounded-tr-xs ml-auto font-medium"
                                  : "bg-white text-stone-800 rounded-tl-xs"
                              }`}
                            >
                              <p className="whitespace-pre-line">{msg.content}</p>
                            </div>
                            <span className="text-[9px] text-stone-400 mt-1 select-none font-semibold px-1">
                              {msg.timestamp}
                            </span>
                          </div>
                        </div>
                      ))}

                      {/* AI Typing Indicator */}
                      {isAiTyping && (
                        <div className="flex items-start gap-2.5 justify-start">
                          <div className="w-7 h-7 rounded-full bg-yellow-100 flex items-center justify-center border border-yellow-400/20 shrink-0">
                            <Sparkles className="w-3.5 h-3.5 text-amber-500 animate-spin" />
                          </div>
                          <div className="p-3 bg-white text-stone-400 rounded-2xl rounded-tl-xs text-xs flex gap-1 items-center shadow-xs">
                            <span className="w-1.5 h-1.5 rounded-full bg-stone-400 animate-bounce delay-100" />
                            <span className="w-1.5 h-1.5 rounded-full bg-stone-400 animate-bounce delay-200" />
                            <span className="w-1.5 h-1.5 rounded-full bg-stone-400 animate-bounce delay-300" />
                          </div>
                        </div>
                      )}

                      <div ref={chatBottomRef} />
                    </div>

                    {/* Pre-written quick trigger block */}
                    <div className="px-4 py-2 border-t border-stone-100 bg-[#fcf9f8]/95 space-y-2">
                      <div className="flex gap-2">
                        {/* Interactive prompt assist clickers */}
                        {!isChatSubmitted && (
                          <button
                            onClick={() => handleSendMessage("1-2小时，就在家附近吧")}
                            className="text-[10px] font-bold py-1.5 px-3 rounded-full bg-stone-50 hover:bg-stone-100 text-stone-600 border border-stone-200/50"
                          >
                            📍 就在附近
                          </button>
                        )}
                        <button
                          onClick={() => handleSendMessage("想喝咖啡或者看书")}
                          className="text-[10px] font-bold py-1.5 px-3 rounded-full bg-stone-50 hover:bg-stone-100 text-stone-600 border border-stone-200/50"
                        >
                          ☕ 一杯手冲
                        </button>
                        <button
                          onClick={() => handleSendMessage("有什么免费的地方？")}
                          className="text-[10px] font-bold py-1.5 px-3 rounded-full bg-stone-50 hover:bg-stone-100 text-stone-600 border border-stone-200/50"
                        >
                          💰 零预算
                        </button>
                      </div>

                      {/* Step transition prompt */}
                      <div className="bg-amber-500/10 border border-amber-400/20 rounded-xl p-3 flex items-start gap-2.5">
                        <span className="p-1 px-2 rounded bg-amber-400 text-neutral-900 font-bold text-[10px] uppercase select-none shrink-0 tracking-wider">
                          下一步
                        </span>
                        <div>
                          <p className="text-[11px] font-bold text-[#725c00]">
                            倾听结束？开启定制推荐
                          </p>
                          <p className="text-[10px] text-[#725c00]/80 leading-normal mt-0.5">
                            点击下方按钮，AI 将根据你此刻流露的想法，专为你定制精选的 3 个一人独处漫步和静心空间方案。
                          </p>
                        </div>
                      </div>

                      {/* Large Quick Generator Action */}
                      <button
                        onClick={triggerAutoPlanGeneration}
                        className="w-full bg-gradient-to-r from-neutral-900 to-neutral-950 hover:from-neutral-950 hover:to-black text-amber-400 text-[11px] font-bold py-3.5 px-4 rounded-xl shadow-md flex justify-center items-center gap-2 active:scale-95 duration-150 transition-all border border-amber-400/30"
                      >
                        <Sparkles className="w-3.5 h-3.5 text-amber-400 fill-amber-400 animate-pulse" />
                        分析想法，生成 3 个一人秘密方案 →
                      </button>

                      {/* Input controls */}
                      <div className="flex gap-2 items-center bg-white rounded-full p-1 border border-stone-200 shadow-sm mt-2">
                        <button className="p-1.5 rounded-full text-stone-400 hover:text-stone-600 cursor-pointer">
                          <PlusCircle className="w-4 h-4" />
                        </button>
                        <input
                          type="text"
                          value={inputText}
                          onChange={(e) => setInputText(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && handleSendMessage()}
                          placeholder="发消息，或描述你想去的地方..."
                          className="flex-1 min-w-0 px-2 py-1 text-xs focus:outline-hidden bg-transparent border-none focus:ring-0 text-neutral-800"
                        />
                        <button className="p-1.5 rounded-full text-stone-400 hover:text-stone-600 cursor-pointer">
                          <Mic className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleSendMessage()}
                          className="p-2 rounded-full bg-amber-400 hover:bg-amber-300 text-neutral-900 cursor-pointer shadow-xs active:scale-95 transition-all"
                        >
                          <Send className="w-3 h-3" />
                        </button>
                      </div>
                    </div>

                  </div>
                )}

                {/* 3. SCREEN: SOLUTIONS (3个一人定制方案) */}
                {currentScreen === "solutions" && (
                  <div className="px-5 py-3 space-y-5">
                    
                    {/* Title and context */}
                    <div>
                      <div className="text-[10px] font-mono font-bold tracking-widest text-[#725c00] bg-yellow-500/10 px-2.5 py-1 rounded inline-block mb-1.5 uppercase">
                        定制方案 | 一人专属定制推荐
                      </div>
                      <h2 className="text-xl font-bold font-display-lg text-neutral-900 leading-tight">
                        AI 为你定制了 3 个一人方案
                      </h2>
                      <p className="text-[#4e4632] text-xs font-body-md mt-1">
                        精选最懂一个人的秘密漫步行程，拒绝无意义人群社交与嘈杂 🍃
                      </p>
                    </div>

                    {/* AI Insight Card */}
                    <div className="p-4 bg-white/70 backdrop-blur-md rounded-2xl border border-amber-200/40 relative shadow-xs flex items-start gap-3.5">
                      <div className="p-2.5 rounded-full bg-amber-400 text-neutral-900 shrink-0">
                        <Sparkles className="w-4 h-4 text-amber-950 fill-amber-950" />
                      </div>
                      <div>
                        <h4 className="text-[10px] font-bold uppercase tracking-wider text-[#725c00] mb-0.5">AI 洞察</h4>
                        <p className="text-[11px] text-[#4e4632] leading-relaxed">
                          “检测到你当前能量值稍低，更适合轻松、低压力、可独处的放松型活动。这些方案能帮你温和地恢复状态。”
                        </p>
                      </div>
                    </div>

                    {/* 3 Bento Items Plan */}
                    <div className="space-y-4">
                      {wanderPlans.map((plan) => (
                        <div
                          key={plan.id}
                          className={`bg-white rounded-2xl overflow-hidden shadow-xs border transition-all duration-200 p-4 shrink-0 cursor-pointer ${
                            selectedPlanId === plan.id
                              ? "border-amber-400 ring-2 ring-amber-400/30 bg-amber-50/10"
                              : "border-stone-200/50"
                          }`}
                          onClick={() => setSelectedPlanId(plan.id)}
                        >
                          {/* Image inside */}
                          <div className="relative h-44 rounded-xl overflow-hidden mb-3.5">
                            <img
                              src={plan.image}
                              alt={plan.title}
                              className="w-full h-full object-cover"
                              referrerPolicy="no-referrer"
                            />
                            <div className="absolute top-3 left-3 flex gap-2">
                              <span className="bg-neutral-900/80 text-white font-label-md text-[9px] px-2.5 py-0.5 rounded-full">
                                {plan.category}
                              </span>
                            </div>
                          </div>

                          {/* Chips */}
                          <div className="flex flex-wrap gap-1.5 mb-2.5">
                            {plan.subChips.map((chip, n) => (
                              <span 
                                key={n}
                                className="px-2 py-0.5 rounded-full bg-stone-100 text-[#4e4632] text-[10px] font-medium"
                              >
                                {chip}
                              </span>
                            ))}
                          </div>

                          <h3 className="text-md font-bold text-stone-900 leading-snug">
                            {plan.title}
                          </h3>

                          {/* Plan parameters */}
                          <div className="flex gap-4 text-stone-500 text-[11px] font-semibold tracking-wide my-2 pt-1">
                            <span className="flex items-center gap-1">
                              <Clock className="w-3.5 h-3.5" />
                              {plan.duration}
                            </span>
                            <span className="flex items-center gap-1">
                              <CreditCard className="w-3.5 h-3.5" />
                              {plan.cost}
                            </span>
                            <span className="flex items-center gap-1">
                              <MapPin className="w-3.5 h-3.5" />
                              {plan.area || "附近"}
                            </span>
                          </div>

                          {/* recommendation details */}
                          <div className="p-3 bg-stone-50 border-l-3 border-[#725c00] rounded-r-lg text-[10px] text-[#4e4632] italic mt-2">
                            {plan.quote}
                          </div>

                          {/* Select button */}
                          <div className="mt-4">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedPlanId(plan.id);
                                handleBookNow();
                              }}
                              className={`w-full py-3 rounded-full text-xs font-bold transition-all flex justify-center items-center gap-1.5 active:scale-95 cursor-pointer ${
                                selectedPlanId === plan.id
                                  ? "bg-amber-400 text-neutral-950"
                                  : "bg-white border border-stone-800 text-stone-800"
                              }`}
                            >
                              <span>选择并让 AI 一键安排</span> 
                              <ArrowRight className="w-3.5 h-3.5" />
                            </button>
                          </div>

                        </div>
                      ))}
                    </div>

                    {/* Booking stick bar */}
                    <div className="pt-3 border-t border-stone-200 space-y-3">
                      {/* Step transition prompt */}
                      <div className="bg-amber-500/10 border border-amber-400/20 rounded-xl p-3.5 flex items-start gap-3">
                        <span className="p-1 px-2 rounded bg-amber-400 text-neutral-900 font-bold text-[10px] uppercase select-none shrink-0 tracking-wider">
                          下一步
                        </span>
                        <div>
                          <p className="text-[11.5px] font-bold text-[#725c00] flex items-center gap-1">
                            方案合心意？让 AI 一键安排
                          </p>
                          <p className="text-[10px] text-[#725c00]/80 leading-normal mt-0.5">
                            AI 将帮你锁死静音角落位置、自动定制最佳树荫慢行避暑路径。
                          </p>
                        </div>
                      </div>

                      <button
                        onClick={handleBookNow}
                        className="w-full py-4 rounded-full bg-amber-400 text-neutral-900 text-sm font-bold shadow-md active:scale-95 transition-all flex items-center justify-center gap-2 cursor-pointer"
                      >
                        <Calendar className="w-4 h-4 shrink-0" />
                        让 AI 帮我一键安排这个方案 →
                      </button>
                      
                      <div className="flex gap-2.5 mt-2.5">
                        <button 
                          onClick={swapDailyTask}
                          className="flex-1 bg-stone-100 font-bold py-2.5 rounded-full hover:bg-stone-200 text-stone-700 text-xs flex items-center justify-center gap-1.5 cursor-pointer active:scale-95"
                        >
                          <RefreshCw className="w-3.5 h-3.5 text-stone-600" />
                          换一批
                        </button>
                        <button 
                          onClick={() => popScreen()}
                          className="flex-1 bg-stone-100 font-bold py-2.5 rounded-full hover:bg-stone-200 text-stone-700 text-xs flex items-center justify-center gap-1.5 cursor-pointer active:scale-95"
                        >
                          <Sliders className="w-3.5 h-3.5 text-stone-600" />
                          重新调整
                        </button>
                      </div>
                    </div>

                  </div>
                )}

                {/* 4. SCREEN: AI正在为你安排 (一键预约进展) */}
                {currentScreen === "booking" && (
                  <div className="px-5 py-3 space-y-5">
                    
                    {/* Page title */}
                    <div>
                      <div className="text-[10px] font-mono font-bold tracking-widest text-[#006c4f] bg-green-500/10 px-2.5 py-1 rounded inline-block mb-1.5 uppercase">
                        AI 正在执行安排 | 一键免打扰托管
                      </div>
                      <h2 className="text-xl font-bold font-display-lg text-neutral-900 leading-tight">
                        AI 正在为你安排
                      </h2>
                      <p className="text-stone-500 text-xs mt-1">
                        自动帮你预约席位、锁定最佳独处角落并规划树荫避护路线 🌳
                      </p>
                    </div>

                    {/* Solutions Summary header */}
                    <div className="p-4 bg-white rounded-2xl shadow-[0_4px_25px_rgba(0,0,0,0.03)] border border-stone-200/60 shrink-0">
                      <div className="flex justify-between items-center mb-2">
                        <span className="px-2.5 py-0.5 bg-teal-50 text-teal-700 rounded-full font-label-md text-[10px] font-bold">
                          静谧午后
                        </span>
                        <Sparkles className="w-4 h-4 text-amber-500" />
                      </div>
                      
                      <h3 className="font-bold text-sm text-stone-900 leading-snug">
                        静谧午后：河边漫步与手冲咖啡
                      </h3>

                      <div className="flex gap-3 mt-2 text-[10px] text-stone-500 font-semibold uppercase">
                        <span className="flex items-center gap-0.5"><Clock className="w-3.5 h-3.5 text-[#725c00]" /> 1.5h</span>
                        <span className="flex items-center gap-0.5"><CreditCard className="w-3.5 h-3.5 text-stone-600" /> ¥40</span>
                        <span className="flex items-center gap-0.5"><MapPin className="w-3.5 h-3.5 text-teal-600" /> 滨江公园区域</span>
                      </div>

                      <p className="text-[11px] text-[#4e4632] mt-3.5 italic border-l-2 border-[#725c00] pl-2">
                        “享受流水与咖啡香的感官治愈。”
                      </p>
                    </div>

                    {/* AI Execution progress line */}
                    <div className="p-4 bg-stone-50 rounded-2xl border border-stone-200/40 relative">
                      <h4 className="text-[11px] font-bold text-[#725c00] mb-4 flex items-center gap-1.5 uppercase tracking-wide">
                        <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
                        AI 执行进度
                      </h4>

                      <div className="space-y-4 relative pl-3.5">
                        {/* Progress line indicator */}
                        <div className="absolute left-[6px] top-1 bottom-1 w-[2px] bg-stone-200/80" />

                        {/* Step 1 */}
                        <div className="flex items-start gap-3 relative">
                          <div className={`absolute -left-[14px] top-0.5 w-[14px] h-[14px] rounded-full flex items-center justify-center ${
                            bookingProgress >= 1 ? "bg-amber-400 text-neutral-900" : "bg-stone-200 text-stone-400"
                          }`}>
                            <Check className="w-2.5 h-2.5" />
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-stone-800">
                              已为你匹配最适合一个人的咖啡馆
                            </p>
                          </div>
                        </div>

                        {/* Step 2 */}
                        <div className="flex items-start gap-3 relative">
                          <div className={`absolute -left-[14px] top-0.5 w-[14px] h-[14px] rounded-full flex items-center justify-center ${
                            bookingProgress >= 2 ? "bg-amber-400 text-neutral-900" : "bg-stone-200 text-stone-400"
                          }`}>
                            <Check className="w-2.5 h-2.5" />
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-stone-800">
                              已锁定今日 15:30 黄金窗边位
                            </p>
                          </div>
                        </div>

                        {/* Step 3 */}
                        <div className="flex items-start gap-3 relative">
                          <div className={`absolute -left-[14px] top-0.5 w-[14px] h-[14px] rounded-full flex items-center justify-center ${
                            bookingProgress >= 3 ? "bg-amber-400 text-neutral-900" : "bg-stone-200 text-stone-400"
                          }`}>
                            <Check className="w-2.5 h-2.5" />
                          </div>
                          <div>
                            <p className="text-xs font-semibold text-stone-800">
                              已规划最优步行避暑路线
                            </p>
                          </div>
                        </div>

                        {/* Wait trigger */}
                        <div className="flex items-start gap-3 relative">
                          <div className="absolute -left-[14px] top-0.5 w-[14px] h-[14px] rounded-full bg-amber-100 text-amber-600 flex items-center justify-center animate-spin">
                            <Clock className="w-2.5 h-2.5" />
                          </div>
                          <div>
                            <p className="text-xs font-bold text-[#725c00]">
                              等待你的最后确认
                            </p>
                          </div>
                        </div>

                      </div>
                    </div>

                    {/* Recommended Merchant box details */}
                    <div className="bg-white rounded-2xl overflow-hidden border border-stone-200 shadow-xs cursor-pointer hover:shadow-md transition-shadow" onClick={() => pushScreen("index")}>
                      <div className="relative h-32">
                        <img 
                          src={ASSETS.riversideCoffeeB} 
                          alt="Riverside Coffee" 
                          className="w-full h-full object-cover select-none"
                          referrerPolicy="no-referrer"
                        />
                        <div className="absolute top-3 right-3 bg-white/80 backdrop-blur px-2 py-0.5 rounded-full text-[10px] font-bold text-neutral-800 flex items-center gap-0.5 border border-stone-200/50">
                          <Star className="w-3.5 h-3.5 text-amber-500 fill-amber-500" />
                          <span>4.8</span>
                        </div>
                      </div>

                      <div className="p-4">
                        <div className="flex justify-between items-center mb-1">
                          <h4 className="text-sm font-bold text-stone-900 leading-tight">Riverside Brew 河畔咖啡</h4>
                          <span className="text-[10px] text-stone-500 tracking-wide">距离 800m</span>
                        </div>
                        <p className="text-[#4e4632] text-[11px] mb-3 leading-tight line-clamp-1">
                          “提供单人静谧阅读区，窗外江景极佳，非常适合你现在的放松需求。”
                        </p>
                        
                        <div className="bg-amber-50/70 p-2.5 rounded-xl border border-amber-200/20 flex items-center justify-between text-xs text-[#725c00]">
                          <span className="font-semibold flex items-center gap-1.5">
                            <Calendar className="w-3.5 h-3.5 text-amber-500" />
                            预约时间 15:30 (今日)
                          </span>
                          <ArrowRight className="w-3.5 h-3.5 text-[#725c00]" />
                        </div>
                      </div>
                    </div>

                    {/* Routing suggest box */}
                    <div className="p-4 bg-orange-50/50 border border-orange-200/50 rounded-2xl flex gap-3 shadow-xs">
                      <div className="p-2 bg-[#725c00] text-white rounded-full flex items-center justify-center shrink-0">
                        <Footprints className="w-5 h-5" />
                      </div>
                      <div>
                        <div className="flex items-center gap-1">
                          <h4 className="font-bold text-xs text-stone-800">步行建议</h4>
                          <span className="text-stone-400 text-[10px]">&middot; 10min</span>
                        </div>
                        <p className="text-[11px] text-[#4e4632] leading-relaxed mt-0.5">
                          沿途经过滨江步道，树荫覆盖率 80%，适合慢走。
                        </p>
                      </div>
                    </div>

                    {/* Booking sticky controllers */}
                    <div className="pt-2 space-y-4">
                      {/* Next Step automated recommendation alert */}
                      <motion.div 
                        initial={{ opacity: 0, scale: 0.95, y: 8 }}
                        animate={{ opacity: 1, scale: 1, y: 0 }}
                        transition={{ delay: 0.1, duration: 0.3 }}
                        className="p-4 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-start gap-3.5 shadow-xs"
                      >
                        <span className="p-2.5 bg-emerald-500 text-white rounded-full flex items-center justify-center shrink-0 shadow-sm animate-pulse">
                          <Footprints className="w-4 h-4" />
                        </span>
                        <div className="space-y-1">
                          <h4 className="font-extrabold text-[12px] text-emerald-900 flex items-center gap-1.5 leading-none">
                            智能推荐：🎒 今日出门挑战
                          </h4>
                          <p className="text-[11px] text-emerald-800 leading-normal">
                            自动代托管与席位预约已百分百就位！窗边无扰席位已被牢牢锁住。让我们直接启动“今日出门挑战”，赋予这次出门一个微小、温暖且减压的行动仪式吧 ✨
                          </p>
                        </div>
                      </motion.div>

                      <button 
                        onClick={() => {
                          setIsBookingConfirmed(true);
                          setCompletedQuests((prev) => prev + 1);
                          setIsChallengeAccepted(true);
                          setCurrentScreen("challenge");
                          alert("🎉 预约就绪！已经帮你预定好了座位和静音空间。下面开启今日出门挑战，迈出轻松的一步吧！🌿");
                        }}
                        className="w-full py-4 bg-gradient-to-r from-amber-400 to-amber-300 hover:from-amber-300 hover:to-amber-200 font-bold text-neutral-900 text-[15px] rounded-full shadow-md flex items-center justify-center gap-2 cursor-pointer transition-transform active:scale-95 duration-100 border border-amber-400/20"
                      >
                        <Zap className="w-4 h-4 shrink-0 fill-neutral-900 animate-bounce" />
                        确认预约并开启出门挑战 →
                      </button>

                      <button 
                        onClick={() => pushScreen("solutions")}
                        className="w-full text-center py-2 text-xs font-bold text-[#725c00] underline mt-1 block cursor-pointer"
                      >
                        调整预约内容
                      </button>
                    </div>

                  </div>
                )}

                {/* 6. SCREEN: RESONANCE ("今天也有人和你一样一个人出发") */}
                {currentScreen === "resonance" && (
                  <div className="px-5 py-3 space-y-5">
                    
                    {/* Header Details */}
                    <div>
                      <div className="text-[10px] font-mono font-bold tracking-widest text-[#725c00] bg-yellow-500/10 px-2.5 py-1 rounded inline-block mb-1.5 uppercase">
                        同城共鸣 | 温暖无压弱社交
                      </div>
                      <h2 className="text-xl font-bold font-display-lg text-neutral-900 leading-tight">
                        今天，也有人和你一样一个人出发
                      </h2>
                      <p className="text-stone-500 text-xs mt-1">
                        你不是唯一一个出发的人。看，城市空隙里许多人正在独自浪漫起步 🟢
                      </p>
                    </div>

                    {/* City Resonance big counter */}
                    <div className="p-4 bg-yellow-50/80 border border-yellow-200/50 rounded-2xl flex gap-3.5 items-center justify-start relative shadow-xs shrink-0">
                      <div className="p-3 rounded-full bg-amber-400 text-neutral-900">
                        <Smile className="w-5 h-5 animate-pulse" />
                      </div>
                      <div>
                        <h4 className="text-[10px] font-bold text-[#725c00] tracking-wider uppercase">城市共鸣</h4>
                        <p className="text-md text-stone-900 leading-tight mt-0.5">
                          今天同城已有 <span className="text-amber-600 font-extrabold text-lg">{resonanceCount}</span> 人漫游出门
                        </p>
                        <p className="text-[10px] text-stone-400 font-semibold mt-1">
                          🟢 附近 3km 内有 {resonanceNearby} 人正在打卡任务中
                        </p>
                      </div>
                    </div>

                    {/* Companion list lines (发现同路人) */}
                    <div className="space-y-3.5">
                      <div className="flex justify-between items-center">
                        <h4 className="text-[13px] font-extrabold text-neutral-800">发现同路人</h4>
                        <span className="text-[10px] text-[#725c00] font-bold underline cursor-pointer" onClick={() => pushScreen("map")}>
                          全部路线 &gt;
                        </span>
                      </div>

                      <div className="space-y-3">
                        {COMMUNITY_LINES.map((line) => (
                          <div 
                            key={line.id}
                            className="p-3 bg-white rounded-2xl border border-stone-200/60 shadow-xs flex items-center justify-between hover:shadow-md transition-shadow shrink-0 cursor-pointer"
                            onClick={() => {
                              setSelectedMerchantId(line.id);
                              pushScreen("index");
                            }}
                          >
                            <div className="flex items-center gap-3">
                              <div className="w-14 h-14 rounded-xl overflow-hidden shrink-0 border border-stone-100">
                                <img 
                                  src={line.image} 
                                  alt={line.title} 
                                  className="w-full h-full object-cover select-none"
                                  referrerPolicy="no-referrer"
                                />
                              </div>

                              <div>
                                <h5 className="text-xs font-bold text-stone-900 leading-tight">
                                  {line.title}
                                </h5>
                                <div className="flex gap-1 mt-1 shrink-0">
                                  {line.tags.map((tag, i) => (
                                    <span 
                                      key={i}
                                      className="px-1.5 py-0.5 rounded text-[8px] bg-[#fcf9f8] text-[#725c00] font-bold"
                                    >
                                      {tag}
                                    </span>
                                  ))}
                                </div>
                              </div>
                            </div>

                            <div className="text-right shrink-0">
                              <p className="text-amber-500 font-extrabold text-xs">{line.selectedCount} 人选择</p>
                              <p className="text-[9px] text-stone-400 font-mono mt-0.5">{line.activeWord}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Double statistical layout cards */}
                    <div className="grid grid-cols-2 gap-3 pb-2.5 select-none">
                      <div className="p-3.5 bg-stone-50 rounded-2xl border border-stone-200/40 text-center flex flex-col items-center justify-center gap-2 shadow-xs">
                        <Clock className="w-6 h-6 text-amber-500 fill-amber-200/50" />
                        <p className="text-[10.5px] leading-snug text-[#4e4632] font-semibold">
                          有 <span className="text-amber-600 font-bold">42</span> 人规划了 1h 内的放空路线
                        </p>
                      </div>

                      <div className="p-3.5 bg-stone-50 rounded-2xl border border-stone-200/40 text-center flex flex-col items-center justify-center gap-2 shadow-xs">
                        <BookOpen className="w-6 h-6 text-[#006c4f] fill-green-100/30" />
                        <p className="text-[10.5px] leading-snug text-[#4e4632] font-semibold">
                          有 <span className="text-teal-600 font-bold">15</span> 人偏好安静的角落和书店
                        </p>
                      </div>
                    </div>

                    {/* Companion light-up panel block */}
                    <div className="relative pt-4 text-center">
                      <h4 className="text-sm font-bold text-stone-900">点亮一份陪伴</h4>
                      
                      <div className="flex flex-col gap-3 mt-3 relative">
                        
                        {/* Floating heart loops container */}
                        <div className="absolute inset-x-0 bottom-20 h-32 pointer-events-none overflow-hidden select-none z-[80]">
                          <AnimatePresence>
                            {floatingHearts.map((heart) => (
                              <motion.div
                                key={heart.id}
                                className="absolute text-rose-500 text-lg"
                                style={{ left: `${heart.left}%` }}
                                initial={{ opacity: 0, y: 70, scale: 0.6 }}
                                animate={{ opacity: 1, y: 0, scale: 1.2 }}
                                exit={{ opacity: 0, y: -80, scale: 0.8 }}
                                transition={{ duration: 1.2, ease: "easeOut" }}
                              >
                                <Heart className="w-5 h-5 fill-rose-500" />
                              </motion.div>
                            ))}
                          </AnimatePresence>
                        </div>

                        {/* Button 1: I am setting off too */}
                        <button
                          onClick={() => {
                            if (!departedSelf) {
                              setResonanceCount((prev) => prev + 1);
                              setResonanceNearby((prev) => prev + 1);
                              setDepartedSelf(true);
                              alert("🚀 您已顺利登记加入今日同城漫行。玩得开心！");
                            } else {
                              alert("您当前已经出发啦！好好享受这一小段属于你的一人时光 ✨");
                            }
                          }}
                          className={`w-full py-4 rounded-full font-bold text-sm shadow-md cursor-pointer transition-all active:scale-95 duration-100 flex items-center justify-center gap-2 ${
                            departedSelf 
                              ? "bg-stone-200 text-stone-400 cursor-not-allowed" 
                              : "bg-amber-400 text-neutral-900"
                          }`}
                        >
                          <Smile className="w-4 h-4 text-neutral-900 fill-neutral-900" />
                          {departedSelf ? "我也出发了 (已点亮)" : "我也出发了"}
                        </button>

                        {/* Button 2: Send thumbs to companion */}
                        <button
                          onClick={handleLikeInteractions}
                          className="w-full py-3.5 bg-white border border-stone-800 font-bold text-stone-800 text-sm rounded-full cursor-pointer transition-all active:scale-95 duration-100 flex items-center justify-center gap-1.5"
                        >
                          <Heart className="w-4 h-4 text-rose-500 fill-rose-500" />
                          为同路人点亮一下 ({likedCount})
                        </button>
                      </div>

                      <p className="text-[10px] text-stone-400 font-mono tracking-wide mt-3 pb-3">
                        ✓ 所有漫步数据已完全匿名，不展示具体GPS位置，保障安全独处。
                      </p>
                    </div>

                  </div>
                )}

                {/* 7. SCREEN: MAP / INSTANCES (你的城市副本) */}
                {currentScreen === "map" && (
                  <div className="px-5 py-3 space-y-4">
                    
                    {/* Header Details */}
                    <div>
                      <div className="text-[10px] font-mono font-bold tracking-widest text-[#00694d] bg-green-500/10 px-2.5 py-1 rounded inline-block mb-1.5 uppercase">
                        城市副本 | 独处轨迹与解密打卡
                      </div>
                      <h2 className="text-xl font-bold font-display-lg text-neutral-900 leading-tight">
                        你的城市副本
                      </h2>
                      <p className="text-[#4e4632] text-xs font-body-md mt-1">
                        把一个人的出门，变成像游戏副本一样的奇妙探索与角落打卡 🚶🗺️
                      </p>
                      
                      <div className="inline-flex items-center gap-1 bg-amber-50 text-[#725c00] py-1 px-3 mt-2 rounded-full border border-amber-200/30 font-label-md text-[11px] font-bold">
                        <MapPin className="w-3.5 h-3.5 animate-bounce text-amber-500" />
                        <span>{mapCenterMsg}</span>
                      </div>
                    </div>

                    {/* Interactive stylized city map section */}
                    <div className="relative w-full aspect-[4/3] rounded-2xl overflow-hidden shadow-[0_4px_25px_rgba(0,0,0,0.06)] border border-stone-200 block">
                      
                      {recalculatingMap ? (
                        <div className="absolute inset-0 bg-stone-100/90 flex flex-col items-center justify-center z-30 space-y-3">
                          <Sparkles className="w-8 h-8 text-amber-500 animate-spin" />
                          <p className="text-xs font-bold text-[#725c00]">正在微调GPS定位并搜索一人友好商家...</p>
                        </div>
                      ) : null}

                      {/* Map backdrop image */}
                      <img 
                        src={ASSETS.mapBox} 
                        alt="Citymap" 
                        className="absolute inset-0 w-full h-full object-cover select-none pointer-events-none"
                        referrerPolicy="no-referrer"
                      />

                      {/* Overlays / Map pins markers */}
                      {/* Compass marker */}
                      <div className="absolute top-[85px] left-[150px] relative">
                        <div className="relative w-7 h-7 flex items-center justify-center cursor-pointer active:scale-90" onClick={() => alert("您目前在：上海市黄浦区滨江步域中心点")}>
                          <div className="absolute inset-0 bg-amber-500 rounded-full animate-ping opacity-30" />
                          <div className="relative w-5 h-5 bg-amber-500 rounded-full border border-white shadow-md flex items-center justify-center">
                            <div className="w-2.5 h-2.5 bg-neutral-900 rounded-full" />
                          </div>
                        </div>
                      </div>

                      {/* Check-in completed pin */}
                      <div className="absolute top-[50px] right-[70px]">
                        <div 
                          onClick={() => alert("已完成打卡的：静谧小吃餐馆。探索值已增加！")}
                          className="w-10 h-10 rounded-full bg-teal-500 shadow-md border-2 border-white flex items-center justify-center text-white cursor-pointer active:scale-95 duration-100"
                        >
                          <Store className="w-4.5 h-4.5" />
                        </div>
                      </div>

                      {/* Solo friendly highlight indicator */}
                      <div className="absolute bottom-[20px] left-[40px] flex flex-col items-center">
                        <div className="bg-white/95 backdrop-blur px-2.5 py-0.5 rounded-full shadow-md text-[9px] font-bold text-[#725c00] border border-amber-200 mb-0.5">
                          一人友好 🌟
                        </div>
                        <div 
                          onClick={() => pushScreen("index")}
                          className="w-10 h-10 rounded-full bg-amber-400 shadow-md border-2 border-white flex items-center justify-center text-neutral-900 animate-bounce cursor-pointer active:scale-95 duration-100"
                        >
                          <BookOpen className="w-4.5 h-4.5" />
                        </div>
                      </div>

                      {/* Re-localize GPS trigger button */}
                      <button 
                        onClick={() => {
                          setRecalculatingMap(true);
                          setTimeout(() => {
                            setRecalculatingMap(false);
                            setMapCenterMsg("上海 滨江公园探索中");
                          }, 1500);
                        }}
                        className="absolute bottom-3 right-3 bg-white/90 backdrop-blur pl-3 pr-4 py-2 rounded-full cursor-pointer shadow-sm active:scale-95 transition-all text-[11px] font-bold text-amber-600 flex items-center gap-1.5 border border-stone-200"
                      >
                        <Compass className="w-3.5 h-3.5" />
                        重新定位
                      </button>
                    </div>

                    {/* Progress slider scroll slider stats */}
                    <div className="flex gap-3 overflow-x-auto py-2 shrink-0 hide-scrollbar scroll-smooth">
                      <div className="min-w-[125px] p-3.5 bg-white rounded-xl border border-stone-200/50 flex flex-col gap-1 shadow-xs">
                        <span className="text-[10px] text-stone-400 font-bold">已点亮</span>
                        <span className="text-sm font-extrabold text-[#725c00]">0 个商家</span>
                      </div>
                      <div className="min-w-[125px] p-3.5 bg-white rounded-xl border border-stone-200/50 flex flex-col gap-1 shadow-xs">
                        <span className="text-[10px] text-stone-400 font-bold">已完成</span>
                        <span className="text-sm font-extrabold text-[#725c00]">{completedQuests} 个任务</span>
                      </div>
                      <div className="min-w-[125px] p-3.5 bg-white rounded-xl border border-stone-200/50 flex flex-col gap-1 shadow-xs">
                        <span className="text-[10px] text-stone-400 font-bold">探索进度</span>
                        <span className="text-sm font-extrabold text-neutral-900">0%</span>
                        <div className="w-full bg-stone-100 h-1.5 rounded-full overflow-hidden mt-1">
                          <div className="bg-[#725c00] h-full w-[0%]" />
                        </div>
                      </div>
                    </div>

                    {/* Nearby recommend list */}
                    <div className="space-y-3">
                      <h4 className="text-[13px] font-extrabold text-neutral-800">附近副本建议</h4>
                      
                      <div className="space-y-3">
                        {RECOMMENDED_PLACES.map((place) => (
                          <div 
                            key={place.id}
                            className="bg-white rounded-2xl p-3 border border-stone-200 shadow-xs flex gap-3 cursor-pointer hover:shadow-md transition-shadow"
                            onClick={() => pushScreen("index")}
                          >
                            <div className="w-20 h-20 rounded-xl overflow-hidden shrink-0 border border-stone-100">
                              <img 
                                src={place.image} 
                                alt={place.name} 
                                className="w-full h-full object-cover select-none"
                                referrerPolicy="no-referrer"
                              />
                            </div>

                            <div className="flex-1 flex flex-col justify-between overflow-hidden">
                              <div>
                                <h5 className="text-xs font-bold text-stone-900 leading-tight truncate">
                                  {place.name}
                                </h5>
                                <div className="flex items-center gap-1.5 mt-1 select-none">
                                  <div className="flex text-amber-500">
                                    <Star className="w-3 h-3 fill-amber-500" />
                                    <Star className="w-3 h-3 fill-amber-500" />
                                    <Star className="w-3 h-3 fill-amber-500" />
                                    <Star className="w-3 h-3 fill-amber-500" />
                                    <Star className="w-3 h-3 fill-amber-500" />
                                  </div>
                                  <span className="text-[9px] text-[#4e4632] leading-none">
                                    今日 {place.checkinsToday} 人已打卡
                                  </span>
                                </div>
                              </div>

                              <button
                                className={`w-full py-1.5 rounded-full text-[10px] font-bold cursor-pointer transition-transform shrink-0 ${
                                  place.activityType === "checkin"
                                    ? "bg-amber-400 text-neutral-950 hover:bg-amber-300"
                                    : "bg-white border border-stone-800 text-stone-800 hover:bg-stone-50"
                                }`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setPrevScreens((prev) => [...prev, currentScreen]);
                                  setCurrentScreen(place.id === "place-1" ? "index" : "pk");
                                }}
                              >
                                {place.activityText}
                              </button>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Today Dungeon/Instance details */}
                    <div className="p-4 bg-amber-400/95 text-neutral-900 rounded-2xl relative overflow-hidden shadow-md">
                      <div className="absolute -top-10 -right-10 w-24 h-24 bg-white/20 rounded-full blur-2xl select-none" />
                      
                      <div className="relative z-10 space-y-3 shrink-0">
                        <div className="flex items-center gap-1.5 text-xs font-bold shrink-0">
                          <Zap className="w-4 h-4 text-amber-950 fill-amber-950" />
                          <span className="uppercase tracking-wide text-amber-950">今日副本任务</span>
                        </div>
                        
                        <h3 className="text-sm font-extrabold tracking-tight leading-tight">
                          在附近一人友好咖啡店签到
                        </h3>

                        <div className="flex gap-2 shrink-0">
                          <span className="px-2.5 py-0.5 rounded-full bg-white/40 text-[9px] font-bold border border-white/50 flex items-center gap-0.5 shadow-xs">
                            <PlusCircle className="w-3 h-3 text-amber-950" />
                            探索值
                          </span>
                          <span className="px-2.5 py-0.5 rounded-full bg-white/40 text-[9px] font-bold border border-white/50 flex items-center gap-0.5 shadow-xs">
                            <Award className="w-3 h-3 text-amber-950" />
                            咖啡徽章
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Bottom main explore CTA triggers */}
                    <div className="pt-2 space-y-3">
                      {/* Step transition prompt */}
                      <div className="bg-amber-500/10 border border-amber-400/20 rounded-xl p-3.5 flex items-start gap-3">
                        <span className="p-1 px-2 rounded bg-amber-400 text-neutral-900 font-bold text-[10px] uppercase select-none shrink-0 tracking-wider">
                          下一步
                        </span>
                        <div>
                          <p className="text-[11px] font-bold text-[#725c00]">
                            完成探索？看看温暖的同路人
                          </p>
                          <p className="text-[10px] text-[#725c00]/80 leading-normal mt-0.5">
                            点击下方，可以查阅【发现同路人】，和同样在户外漫行独处的朋友发生无压力弱社交共鸣。
                          </p>
                        </div>
                      </div>

                      <button 
                        onClick={() => {
                          setPrevScreens((prev) => [...prev, currentScreen]);
                          setCurrentScreen("index");
                        }}
                        className="w-full py-4 bg-amber-400 hover:bg-amber-300 font-extrabold text-neutral-950 rounded-full shadow-md flex items-center justify-center gap-1.5 cursor-pointer active:scale-95 duration-100"
                      >
                        <Compass className="w-4 h-4 text-neutral-950" />
                        开始今日副本
                      </button>

                      <button 
                        onClick={() => pushScreen("resonance")}
                        className="w-full text-center py-2 text-xs font-bold text-[#725c00] underline block cursor-pointer"
                      >
                        查看同路人及我的漫行记录 →
                      </button>
                    </div>

                  </div>
                )}

                {/* 8. SCREEN: INDEX DETAILS (一人友好指数/维度分解) */}
                {currentScreen === "index" && (
                  <div className="px-5 py-3 space-y-5">
                    
                    {/* Header parameters */}
                    <div className="text-center select-none">
                      <div className="text-[10px] font-mono font-bold tracking-widest text-teal-700 bg-teal-500/10 px-2.5 py-1 rounded inline-block mb-1.5 uppercase">
                        支撑引擎：一人友好度指数评测
                      </div>
                      <h2 className="text-lg font-bold font-display-lg text-neutral-900 leading-tight">
                        {ROUTE_MERCHANTS[selectedMerchantId as keyof typeof ROUTE_MERCHANTS].name}
                      </h2>
                      <div className="inline-flex items-center bg-stone-100 p-1 px-3 mt-1.5 rounded-full text-[10.5px] font-bold text-stone-500 gap-1 select-none">
                        <Store className="w-3.5 h-3.5 text-[#725c00]" />
                        <span>{ROUTE_MERCHANTS[selectedMerchantId as keyof typeof ROUTE_MERCHANTS].category}</span>
                      </div>
                    </div>

                    {/* Score circular gauge hero widget */}
                    <div className="bg-stone-50 rounded-2xl p-5 border border-stone-200/40 relative flex flex-col items-center shadow-xs">
                      
                      {/* Gradient aura */}
                      <div className="absolute inset-0 bg-gradient-to-br from-amber-400/10 to-transparent z-0 select-none pointer-events-none" />

                      {/* Circular graphics SVG gauge */}
                      <div className="relative z-10 w-28 h-28 mb-3 select-none pointer-events-none">
                        <svg className="w-full h-full" viewBox="0 0 120 120">
                          {/* Background tracker ring */}
                          <circle cx="60" cy="60" r="54" fill="none" stroke="#e5e2e1" strokeWidth="8" />
                          {/* Golden rating progress circle arc */}
                          <circle 
                            cx="60" 
                            cy="60" 
                            r="54" 
                            fill="none" 
                            stroke="#ffd000" 
                            strokeWidth="8" 
                            strokeDasharray="339.292" 
                            strokeDashoffset={339.292 - (ROUTE_MERCHANTS[selectedMerchantId as keyof typeof ROUTE_MERCHANTS].score / 100) * 339.292}
                            strokeLinecap="round"
                            className="transform rotate-[-90deg] origin-[60px_60px]"
                          />
                        </svg>
                        
                        {/* Gauge inner texts */}
                        <div className="absolute inset-0 flex flex-col items-center justify-center">
                          <span className="text-3xl font-extrabold text-[#111] leading-none">
                            {ROUTE_MERCHANTS[selectedMerchantId as keyof typeof ROUTE_MERCHANTS].score}
                          </span>
                          <span className="text-[10px] text-stone-400 mt-1 select-none font-bold">/100</span>
                        </div>
                      </div>

                      <div className="z-10 bg-amber-400 text-stone-900 px-3.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide shrink-0">
                        非常适合一个人
                      </div>

                      {/* AI Summary summary info */}
                      <div className="z-10 bg-white/70 backdrop-blur-md rounded-xl p-3 border border-amber-300/30 font-body-md text-[11px] leading-relaxed text-stone-600 mt-4 flex items-start gap-2.5">
                        <Sparkles className="w-4.5 h-4.5 text-amber-500 shrink-0 mt-0.5" />
                        <p>
                          <span className="font-bold text-neutral-900">AI 总结：</span>
                          {ROUTE_MERCHANTS[selectedMerchantId as keyof typeof ROUTE_MERCHANTS].aiSummary}
                        </p>
                      </div>
                    </div>

                    {/* Dimension bar splits */}
                    <div className="space-y-3 shrink-0">
                      <h3 className="text-[13px] font-extrabold text-neutral-800">核心评估维度</h3>
                      
                      <div className="space-y-3 p-4 bg-stone-50 rounded-2xl border border-stone-200/40 shadow-xs">
                        {ROUTE_MERCHANTS[selectedMerchantId as keyof typeof ROUTE_MERCHANTS].dimensions.map((dim, i) => (
                          <div key={i} className="flex items-center gap-3">
                            <span className="w-20 font-bold text-[11.5px] text-stone-700 text-right leading-none shrink-0 truncate">
                              {dim.label}
                            </span>
                            <div className="flex-1 bg-stone-200 h-2 rounded-full overflow-hidden shrink-0">
                              <div 
                                className="bg-[#725c00] h-full rounded-full" 
                                style={{ width: `${dim.percentage}%` }}
                              />
                            </div>
                            <span className="w-6 text-[10.5px] font-bold font-mono text-stone-400 shrink-0 text-right leading-none">
                              {dim.score}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Data sources grid */}
                    <div className="space-y-3">
                      <h3 className="text-[13px] font-extrabold text-neutral-800">数据来源</h3>
                      
                      <div className="grid grid-cols-3 gap-2 text-center pointer-events-none select-none">
                        <div className="p-2.5 bg-stone-50 rounded-xl border border-stone-200/40 flex flex-col items-center gap-1.5 shadow-xs shrink-0">
                          <Cpu className="w-4 h-4 text-amber-500 shrink-0" />
                          <span className="text-[10px] font-bold text-[#1a1a1a] leading-none shrink-0">AI 自动识别</span>
                          <span className="text-[8px] text-stone-400 leading-tight">菜单与图片分析</span>
                        </div>
                        <div className="p-2.5 bg-stone-50 rounded-xl border border-stone-200/40 flex flex-col items-center gap-1.5 shadow-xs shrink-0">
                          <ThumbsUp className="w-4 h-4 text-[#006c4f] shrink-0" />
                          <span className="text-[10px] font-bold text-[#1a1a1a] leading-none shrink-0">用户反馈</span>
                          <span className="text-[8px] text-stone-400 leading-tight">打卡与真实评价</span>
                        </div>
                        <div className="p-2.5 bg-stone-50 rounded-xl border border-stone-200/40 flex flex-col items-center gap-1.5 shadow-xs shrink-0">
                          <Store className="w-4 h-4 text-stone-600 shrink-0" />
                          <span className="text-[10px] font-bold text-[#1a1a1a] leading-none shrink-0">商家补充</span>
                          <span className="text-[8px] text-stone-400 leading-tight">核实设置与支持</span>
                        </div>
                      </div>
                    </div>

                    {/* How AI utilizes this index guidelines explanation */}
                    <div className="p-4 bg-teal-50/40 border border-teal-200/30 rounded-2xl relative shadow-xs">
                      <div className="absolute top-0 right-0 w-24 h-24 bg-teal-500/5 rounded-full blur-xl select-none pointer-events-none" />
                      <h4 className="text-[13px] font-extrabold text-stone-800 mb-3.5 flex items-center gap-1.5 justify-start shrink-0 relative">
                        <Sparkles className="w-4 h-4 text-teal-600" />
                        这个指数如何帮助 AI 规划方案
                      </h4>

                      <div className="grid grid-cols-2 gap-4 relative">
                        <div className="flex items-start gap-1.5">
                          <Check className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                          <div>
                            <span className="font-bold text-[11px] text-stone-800 block">精准筛选商家</span>
                            <span className="text-[9px] text-stone-400 mt-0.5 block leading-tight">剔除不适合聚餐/单纯派对的冗余场所</span>
                          </div>
                        </div>

                        <div className="flex items-start gap-1.5">
                          <Check className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                          <div>
                            <span className="font-bold text-[11px] text-stone-800 block">匹配当下心情</span>
                            <span className="text-[9px] text-stone-400 mt-0.5 block leading-tight">根据“静谧”或“复古”偏好推荐</span>
                          </div>
                        </div>

                        <div className="flex items-start gap-1.5">
                          <Check className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                          <div>
                            <span className="font-bold text-[11px] text-stone-800 block">推荐到访时间</span>
                            <span className="text-[9px] text-stone-400 mt-0.5 block leading-tight">智能锁定低流量时段，享受独处</span>
                          </div>
                        </div>

                        <div className="flex items-start gap-1.5">
                          <Check className="w-4 h-4 text-teal-600 shrink-0 mt-0.5" />
                          <div>
                            <span className="font-bold text-[11px] text-stone-800 block">顺畅路线规划</span>
                            <span className="text-[9px] text-stone-400 mt-0.5 block leading-tight">结合环境交通指数规划动线</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Bottom fixed controller trigger sheets for solutions gen */}
                    <div className="pt-2 border-t border-stone-200 flex gap-3">
                      <button 
                        onClick={() => popScreen()}
                        className="flex-1 py-3.5 border border-stone-800 text-stone-800 font-bold text-xs rounded-full cursor-pointer hover:bg-stone-50 transition-all active:scale-95 duration-100"
                      >
                        返回商家页
                      </button>

                      <button 
                        onClick={() => {
                          setPrevScreens((prev) => [...prev, currentScreen]);
                          setCurrentScreen("solutions");
                        }}
                        className="flex-[2] py-3.5 bg-amber-400 text-neutral-900 font-bold text-xs rounded-full shadow-md cursor-pointer hover:bg-amber-300 transition-all active:scale-95 duration-100 flex items-center justify-center gap-1.5"
                      >
                        <Sparkles className="w-3.5 h-3.5 text-neutral-900 fill-neutral-900" />
                        用这个商家生成方案
                      </button>
                    </div>

                  </div>
                )}

              </motion.div>
            </AnimatePresence>
          </div>

          {/* LOWER NAVIGATION COHESIVE BAR (1.核心AI流程, 2.行动激励, 3.探索, 4.陪伴) */}
          <nav className="absolute bottom-0 left-0 w-full h-18 bg-[#fcf9f8]/95 backdrop-blur-xl border-t border-stone-200/50 flex justify-around items-center pt-2 pb-safe z-(100) shadow-[0_-2px_15px_rgba(0,0,0,0.02)] select-none">
            {/* Nav item: 1. 核心 AI 流程 */}
            <button
              onClick={() => {
                setPrevScreens([]);
                if (currentScreen !== "chat" && currentScreen !== "solutions" && currentScreen !== "booking") {
                  setCurrentScreen("chat");
                }
              }}
              className={`flex-1 flex flex-col items-center justify-center py-1 transition-all duration-200 cursor-pointer ${
                currentScreen === "chat" || currentScreen === "solutions" || currentScreen === "booking"
                  ? "text-[#725c00] font-bold" 
                  : "text-stone-400 hover:text-stone-500"
              }`}
            >
              <Sparkles className={`w-5 h-5 mb-0.5 ${currentScreen === "chat" || currentScreen === "solutions" || currentScreen === "booking" ? "text-amber-500 fill-amber-400/20" : ""}`} />
              <span className="text-[10px] tracking-wide font-bold">核心 AI 流程</span>
            </button>

            {/* Nav item: 2. 行动激励 (今日挑战) */}
            <button
              onClick={() => {
                setPrevScreens([]);
                setCurrentScreen("challenge");
              }}
              className={`flex-1 flex flex-col items-center justify-center py-1 transition-all duration-200 cursor-pointer ${
                currentScreen === "challenge" ? "text-[#725c00] font-bold" : "text-stone-400 hover:text-stone-500"
              }`}
            >
              <Award className={`w-5 h-5 mb-0.5 ${currentScreen === "challenge" ? "fill-amber-400/20 text-amber-500" : ""}`} />
              <span className="text-[10px] tracking-wide font-bold">今日挑战</span>
            </button>

            {/* Nav item: 3. 探索 (城市副本) */}
            <button
              onClick={() => {
                setPrevScreens([]);
                setCurrentScreen("map");
              }}
              className={`flex-1 flex flex-col items-center justify-center py-1 transition-all duration-200 cursor-pointer ${
                currentScreen === "map" ? "text-[#725c00] font-bold" : "text-stone-400 hover:text-stone-500"
              }`}
            >
              <MapIcon className={`w-5 h-5 mb-0.5 ${currentScreen === "map" ? "text-green-600" : ""}`} />
              <span className="text-[10px] tracking-wide font-bold">城市副本</span>
            </button>

            {/* Nav item: 4. 陪伴 (发现同路人) */}
            <button
              onClick={() => {
                setPrevScreens([]);
                setCurrentScreen("resonance");
              }}
              className={`flex-1 flex flex-col items-center justify-center py-1 transition-all duration-200 cursor-pointer ${
                currentScreen === "resonance" ? "text-[#725c00] font-bold" : "text-stone-400 hover:text-stone-500"
              }`}
            >
              <Smile className={`w-5 h-5 mb-0.5 ${currentScreen === "resonance" ? "fill-pink-500/10 text-pink-500" : ""}`} />
              <span className="text-[10px] tracking-wide font-bold">发现同路人</span>
            </button>
          </nav>

          {/* AI Floating button triggering AI planner */}
          <div className="absolute bottom-22 right-5 z-[95] pointer-events-auto">
            <button
              onClick={() => {
                setPrevScreens((prev) => [...prev, currentScreen]);
                setCurrentScreen("chat");
              }}
              className="w-13 h-13 rounded-full bg-gradient-to-tr from-amber-500 to-amber-300 shadow-[0_4px_16px_rgba(255,208,0,0.4)] flex items-center justify-center border-2 border-white cursor-pointer active:scale-90 hover:scale-105 transition-all duration-200"
            >
              <Sparkles className="w-6 h-6 text-neutral-900 fill-neutral-900" />
            </button>
          </div>

        </div>

      </div>

    </div>
  );
}
