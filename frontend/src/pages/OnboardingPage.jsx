import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  FiArrowRight,
  FiBookOpen,
  FiCheckCircle,
  FiCode,
  FiFileText,
  FiLayers,
  FiStar,
  FiTarget,
  FiUploadCloud,
  FiUserCheck,
  FiZap,
} from "react-icons/fi";
import { RiRobot2Line } from "react-icons/ri";

const featureCards = [
  {
    title: "Smart Document Analysis",
    description:
      "Upload your resume and job description. Our AI extracts key information about the company, role, and requirements.",
    icon: FiUploadCloud,
  },
  {
    title: "Skill Gap Analysis",
    description:
      "Identify exactly what skills you need to develop based on the job requirements versus your current expertise.",
    icon: FiTarget,
  },
  {
    title: "Personalized Learning Paths",
    description: "Get curated resources and structured paths to bridge your gaps efficiently.",
    icon: FiBookOpen,
  },
  {
    title: "HR Round Practice",
    description: "Practice common HR questions with profile-aware coaching tuned to your target role.",
    icon: FiUserCheck,
  },
  {
    title: "Technical Interview Prep",
    description: "Access role-specific technical questions, MCQs, and explanations to build confidence.",
    icon: FiCode,
  },
  {
    title: "Resume Enhancement",
    description: "Receive actionable resume improvements tailored to the role you are applying for.",
    icon: FiFileText,
  },
];

const processSteps = [
  {
    title: "Upload Documents",
    description: "Paste or upload your resume and the job description you are targeting.",
  },
  {
    title: "Get Analysis",
    description: "Receive insights on role fit, company context, and required skill expectations.",
  },
  {
    title: "Learn and Practice",
    description: "Follow personalized learning paths and practice interview questions.",
  },
  {
    title: "Ace Your Interview",
    description: "Walk into your interview confident, prepared, and role-ready.",
  },
];

const storyCards = [
  {
    quote: "PrepWise helped me identify exactly what I was missing. I got an offer from my dream company within 2 weeks.",
    author: "Sarah Chen",
    role: "Software Engineer at Meta",
  },
  {
    quote: "The HR practice was a game-changer. I walked in knowing exactly how to structure every answer.",
    author: "James Rodriguez",
    role: "Product Manager at Google",
  },
  {
    quote: "The skill gap analysis showed me what to improve first. I upskilled fast and landed interviews confidently.",
    author: "Priya Sharma",
    role: "Frontend Developer at Stripe",
  },
];

export default function OnboardingPage() {
  const navigate = useNavigate();
  const sectionRefs = useRef([]);
  const sectionExitTimersRef = useRef({});
  const [visibleSections, setVisibleSections] = useState({ 0: true });
  const orbARef = useRef(null);
  const orbBRef = useRef(null);
  const orbCRef = useRef(null);
  const lastScrollYRef = useRef(0);
  const flashTimeoutRef = useRef(null);
  const [scrollFlash, setScrollFlash] = useState({ active: false, direction: "down" });

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          const index = Number(entry.target.getAttribute("data-section-index"));
          if (!Number.isNaN(index)) {
            if (entry.isIntersecting) {
              if (sectionExitTimersRef.current[index]) {
                clearTimeout(sectionExitTimersRef.current[index]);
                delete sectionExitTimersRef.current[index];
              }
              setVisibleSections((prev) => {
                if (prev[index]) return prev;
                return { ...prev, [index]: true };
              });
            } else {
              if (sectionExitTimersRef.current[index]) {
                clearTimeout(sectionExitTimersRef.current[index]);
              }
              // Small delay prevents flicker when users fast-scroll across section edges.
              sectionExitTimersRef.current[index] = setTimeout(() => {
                setVisibleSections((prev) => {
                  if (!prev[index]) return prev;
                  return { ...prev, [index]: false };
                });
                delete sectionExitTimersRef.current[index];
              }, 160);
            }
          }
        });
      },
      { threshold: 0.22, rootMargin: "0px 0px -12% 0px" },
    );

    sectionRefs.current.forEach((node) => {
      if (node) observer.observe(node);
    });

    return () => {
      observer.disconnect();
      Object.values(sectionExitTimersRef.current).forEach((timer) => clearTimeout(timer));
      sectionExitTimersRef.current = {};
    };
  }, []);

  useEffect(() => {
    lastScrollYRef.current = window.scrollY || 0;
    let ticking = false;

    const showFlash = (direction) => {
      setScrollFlash({ active: true, direction });
      if (flashTimeoutRef.current) {
        clearTimeout(flashTimeoutRef.current);
      }
      flashTimeoutRef.current = setTimeout(() => {
        setScrollFlash((prev) => ({ ...prev, active: false }));
        flashTimeoutRef.current = null;
      }, 2000);
    };

    const onScroll = () => {
      if (ticking) return;
      ticking = true;

      window.requestAnimationFrame(() => {
        const nextY = window.scrollY || 0;
        const delta = nextY - lastScrollYRef.current;
        lastScrollYRef.current = nextY;

        if (Math.abs(delta) > 110) {
          showFlash(delta > 0 ? "down" : "up");
        }

        ticking = false;
      });
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (flashTimeoutRef.current) {
        clearTimeout(flashTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    let mouseX = 0;
    let mouseY = 0;
    let scrollY = window.scrollY || 0;
    let rafId = 0;

    const applyMotion = () => {
      rafId = 0;
      const xShift = (mouseX - 0.5) * 2;
      const yShift = (mouseY - 0.5) * 2;

      if (orbARef.current) {
        orbARef.current.style.transform = `translate3d(${xShift * 32}px, ${yShift * 22 + scrollY * 0.05}px, 0)`;
      }
      if (orbBRef.current) {
        orbBRef.current.style.transform = `translate3d(${xShift * -26}px, ${yShift * -18 + scrollY * -0.035}px, 0)`;
      }
      if (orbCRef.current) {
        orbCRef.current.style.transform = `translate3d(${xShift * 14}px, ${yShift * 12 + scrollY * 0.02}px, 0)`;
      }
    };

    const schedule = () => {
      if (!rafId) {
        rafId = window.requestAnimationFrame(applyMotion);
      }
    };

    const handleMouseMove = (event) => {
      mouseX = event.clientX / Math.max(1, window.innerWidth);
      mouseY = event.clientY / Math.max(1, window.innerHeight);
      schedule();
    };

    const handleScroll = () => {
      scrollY = window.scrollY || 0;
      schedule();
    };

    window.addEventListener("mousemove", handleMouseMove, { passive: true });
    window.addEventListener("scroll", handleScroll, { passive: true });
    schedule();

    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("scroll", handleScroll);
      if (rafId) {
        window.cancelAnimationFrame(rafId);
      }
    };
  }, []);

  const onGetStarted = () => navigate("/login");

  function bindSection(index) {
    return (node) => {
      if (!node) return;
      sectionRefs.current[index] = node;
    };
  }

  function sectionClass(index) {
    return visibleSections[index]
      ? "translate-y-0 opacity-100 blur-0"
      : "translate-y-10 opacity-0 blur-[2px]";
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden scroll-smooth bg-[#05070f] text-[#d7d9e1]">
      <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_18%_10%,rgba(95,108,255,0.2),transparent_36%),radial-gradient(circle_at_82%_88%,rgba(0,220,170,0.12),transparent_34%),linear-gradient(180deg,#05070f_0%,#040510_100%)]" />
      <div
        className={`pointer-events-none fixed inset-0 z-[6] transition-opacity duration-700 ${scrollFlash.active ? "opacity-100" : "opacity-0"}`}
      >
        <div
          className={`absolute inset-0 ${scrollFlash.direction === "down"
            ? "bg-[radial-gradient(120%_90%_at_50%_15%,rgba(82,130,255,0.2)_0%,rgba(37,99,235,0.08)_34%,rgba(0,0,0,0)_70%)]"
            : "bg-[radial-gradient(120%_95%_at_50%_85%,rgba(55,153,255,0.18)_0%,rgba(37,99,235,0.07)_36%,rgba(0,0,0,0)_70%)]"}`}
        />
      </div>
      <div
        ref={orbARef}
        className="pointer-events-none fixed -left-28 top-20 h-[26rem] w-[26rem] rounded-full bg-[radial-gradient(circle,rgba(98,112,255,0.34)_0%,rgba(98,112,255,0)_68%)] blur-3xl [transition:transform_350ms_ease-out]"
      />
      <div
        ref={orbBRef}
        className="pointer-events-none fixed -bottom-24 right-0 h-[30rem] w-[30rem] rounded-full bg-[radial-gradient(circle,rgba(0,208,168,0.18)_0%,rgba(0,208,168,0)_68%)] blur-3xl [transition:transform_380ms_ease-out]"
      />
      <div
        ref={orbCRef}
        className="pointer-events-none fixed left-1/2 top-1/3 h-[18rem] w-[18rem] -translate-x-1/2 rounded-full bg-[radial-gradient(circle,rgba(70,179,255,0.2)_0%,rgba(70,179,255,0)_72%)] blur-3xl [transition:transform_320ms_ease-out]"
      />

      <header className="relative z-20 border-b border-[rgba(98,112,255,0.2)] bg-[rgba(5,7,15,0.86)] backdrop-blur-xl">
        <div className="flex w-full items-center justify-between px-5 py-4 sm:px-8 lg:px-12">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-[linear-gradient(135deg,#8a86ff_0%,#4f6dff_100%)] text-white shadow-[0_10px_24px_rgba(93,102,255,0.45)]">
              <RiRobot2Line className="text-lg" />
            </div>
            <div className="min-w-0 leading-tight">
              <p className="text-sm font-semibold text-slate-100">CareerPilot AI</p>
              <p className="text-xs text-slate-400">Interview Preparation OS</p>
            </div>
          </div>

          <div className="ml-4 flex shrink-0 items-center">
            <button
              type="button"
              onClick={onGetStarted}
              className="rounded-full bg-[linear-gradient(135deg,#34c9ff_0%,#497aff_100%)] px-7 py-2.5 text-sm font-semibold text-white transition hover:brightness-110"
            >
              Get Started
            </button>
          </div>
        </div>
      </header>

      <main className="relative z-10">
        <section
          ref={bindSection(0)}
          data-section-index={0}
          className={`mx-auto flex min-h-[calc(100vh-74px)] max-w-7xl flex-col px-5 pt-20 text-center will-change-transform transition-all duration-[1200ms] ease-[cubic-bezier(0.22,1,0.36,1)] sm:px-8 ${sectionClass(0)}`}
        >
          <div>
            <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-[rgba(98,112,255,0.35)] bg-[rgba(29,36,68,0.5)] px-4 py-1 text-sm text-[#8f9cff]">
              <FiZap className="text-sm" />
              AI-Powered Interview Preparation
            </div>
            <h1 className="mx-auto mt-7 max-w-4xl text-5xl font-semibold leading-[1.14] text-slate-100 sm:text-7xl sm:leading-[1.12]">
              Prepare for your
              <span className="block pb-1 bg-[linear-gradient(90deg,#7a83ff_0%,#46b3ff_48%,#00d0a8_100%)] bg-clip-text text-transparent">
                dream job with personalized AI coaching.
              </span>
            </h1>
            <p className="mx-auto mt-8 max-w-2xl text-xl leading-9 text-slate-400">
              Upload your resume and job description to get personalized preparation strategies, skill-gap analysis, and adaptive interview coaching.
            </p>

            <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={onGetStarted}
                className="inline-flex items-center gap-2 rounded-2xl bg-[linear-gradient(135deg,#8e88ff_0%,#5e67ff_100%)] px-7 py-3 text-lg font-semibold text-white shadow-[0_10px_28px_rgba(98,112,255,0.42)] transition hover:brightness-110"
              >
                Get Started Free
                <FiArrowRight className="text-lg" />
              </button>
            </div>

            <div className="mt-12 flex flex-wrap justify-center gap-8 text-lg text-slate-400">
              <p className="inline-flex items-center gap-2"><FiCheckCircle className="text-[#00d0a8]" />No credit card required</p>
              <p className="inline-flex items-center gap-2"><FiCheckCircle className="text-[#00d0a8]" />Instant analysis</p>
              <p className="inline-flex items-center gap-2"><FiCheckCircle className="text-[#00d0a8]" />100% free to start</p>
            </div>
          </div>

            
        </section>

        <section
          ref={bindSection(1)}
          data-section-index={1}
          className={`mx-auto max-w-7xl px-5 py-20 will-change-transform transition-all duration-[1200ms] ease-[cubic-bezier(0.22,1,0.36,1)] sm:px-8 ${sectionClass(1)}`}
        >
          <div className="text-center">
            <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-[rgba(0,208,168,0.28)] bg-[rgba(0,208,168,0.12)] px-4 py-1 text-sm text-[#00d0a8]">
              <FiLayers className="text-sm" />
              Powerful Features
            </div>
            <h2 className="mt-6 text-5xl font-semibold text-slate-100 sm:text-6xl">Everything you need to succeed</h2>
            <p className="mx-auto mt-6 max-w-3xl text-xl leading-8 text-slate-400">
              Our comprehensive platform covers every aspect of interview preparation, from skill development to personalized practice sessions.
            </p>
          </div>

          <div className="mt-14 grid gap-6 lg:grid-cols-3">
            {featureCards.map((item) => {
              const Icon = item.icon;
              return (
                <article
                  key={item.title}
                  className="rounded-3xl border border-[rgba(98,112,255,0.2)] bg-[rgba(8,12,30,0.72)] p-7 shadow-[0_14px_32px_rgba(2,8,24,0.35)] transition duration-300 hover:border-[rgba(98,112,255,0.38)] hover:translate-y-[-3px]"
                >
                  <span className="inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-[rgba(90,95,255,0.16)] text-[#7b84ff]">
                    <Icon className="text-2xl" />
                  </span>
                  <h3 className="mt-6 text-3xl font-semibold text-slate-100">{item.title}</h3>
                  <p className="mt-4 text-lg leading-8 text-slate-400">{item.description}</p>
                </article>
              );
            })}
          </div>
        </section>

        <section
          ref={bindSection(2)}
          data-section-index={2}
          className={`border-y border-[rgba(98,112,255,0.15)] bg-[rgba(2,5,18,0.72)] will-change-transform transition-all duration-[1200ms] ease-[cubic-bezier(0.22,1,0.36,1)] ${sectionClass(2)}`}
        >
          <div className="mx-auto max-w-7xl px-5 py-20 sm:px-8">
            <div className="text-center">
              <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-[rgba(122,131,255,0.35)] bg-[rgba(122,131,255,0.12)] px-4 py-1 text-sm text-[#7a83ff]">
                <FiZap className="text-sm" />
                Simple Process
              </div>
              <h2 className="mt-6 text-5xl font-semibold text-slate-100 sm:text-6xl">How it works</h2>
              <p className="mx-auto mt-6 max-w-2xl text-xl text-slate-400">Get started in minutes with our streamlined preparation process.</p>
            </div>

            <div className="mt-14 grid gap-8 lg:grid-cols-4">
              {processSteps.map((step, index) => (
                <article key={step.title} className="relative rounded-3xl border border-[rgba(98,112,255,0.16)] bg-[rgba(8,11,30,0.58)] p-7">
                  <p className="text-7xl font-semibold text-[rgba(122,131,255,0.34)]">{String(index + 1).padStart(2, "0")}</p>
                  <h3 className="mt-6 text-4xl font-semibold text-slate-100">{step.title}</h3>
                  <p className="mt-3 text-lg leading-8 text-slate-400">{step.description}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section
          ref={bindSection(3)}
          data-section-index={3}
          className={`mx-auto max-w-7xl px-5 py-20 will-change-transform transition-all duration-[1200ms] ease-[cubic-bezier(0.22,1,0.36,1)] sm:px-8 ${sectionClass(3)}`}
        >
          <div className="text-center">
            <div className="mx-auto inline-flex items-center gap-2 rounded-full border border-[rgba(0,208,168,0.35)] bg-[rgba(0,208,168,0.12)] px-4 py-1 text-sm text-[#00d0a8]">
              <FiStar className="text-sm" />
              Success Stories
            </div>
            <h2 className="mt-6 text-5xl font-semibold text-slate-100 sm:text-6xl">Loved by thousands of students</h2>
          </div>

          <div className="mt-14 grid gap-6 lg:grid-cols-3">
            {storyCards.map((story) => (
              <article key={story.author} className="rounded-3xl border border-[rgba(98,112,255,0.2)] bg-[rgba(8,12,30,0.68)] p-8">
                <div className="mb-5 flex gap-1 text-[#7a83ff]">
                  {[0, 1, 2, 3, 4].map((star) => <FiStar key={`${story.author}-${star}`} className="fill-current" />)}
                </div>
                <p className="text-2xl leading-10 text-slate-300">"{story.quote}"</p>
                <p className="mt-8 text-3xl font-semibold text-slate-100">{story.author}</p>
                <p className="mt-1 text-lg text-slate-500">{story.role}</p>
              </article>
            ))}
          </div>
        </section>

        <section
          ref={bindSection(4)}
          data-section-index={4}
          className={`mx-auto max-w-7xl px-5 pb-20 will-change-transform transition-all duration-[1200ms] ease-[cubic-bezier(0.22,1,0.36,1)] sm:px-8 ${sectionClass(4)}`}
        >
          <div className="rounded-[40px] bg-[linear-gradient(135deg,#8f88ff_0%,#706fe0_100%)] px-8 py-16 text-center shadow-[0_20px_48px_rgba(72,79,200,0.42)] sm:px-14">
            <h2 className="text-5xl font-semibold text-[#05070f] sm:text-6xl">Ready to ace your next interview?</h2>
            <p className="mx-auto mt-6 max-w-3xl text-2xl leading-10 text-[rgba(5,7,15,0.76)]">
              Join thousands of successful candidates who prepared with CareerPilot AI. Start your journey to landing your dream role today.
            </p>
            <button
              type="button"
              onClick={onGetStarted}
              className="mt-10 inline-flex items-center gap-2 rounded-2xl bg-[rgba(5,7,15,0.9)] px-8 py-4 text-xl font-semibold text-white transition hover:bg-[rgba(5,7,15,1)]"
            >
              Start Preparing Now
              <FiArrowRight />
            </button>
          </div>
        </section>



      </main>

      <footer className="relative z-20 border-t-0  bg-[rgba(7,10,18,0.95)]">
        <div className="mx-auto flex max-w-8xl flex-col items-center justify-between gap-3 px-5 py-4 text-xs sm:flex-row sm:px-8">
          <p className="font-semibold text-slate-200">CareerPilot AI</p>
          <div className="flex items-center gap-5 text-slate-500">
            <button type="button" className="transition hover:text-slate-300">Privacy Policy</button>
            <button type="button" className="transition hover:text-slate-300">Terms of Service</button>
            <button type="button" className="transition hover:text-slate-300">Cookie Policy</button>
          </div>
          <p className="text-slate-500">© 2026 CareerPilot AI. All rights reserved.</p>
        </div>
      </footer>
    </div>
  );
}

