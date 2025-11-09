import { useEffect, useState, useRef, useMemo } from "react";
import {
  getUniqId,
  scrollToTop,
  ActionViewItemEnum,
  getSessionId,
} from "@/utils";
import querySSE from "@/utils/querySSE";
import { handleTaskData, combineData } from "@/utils/chat";
import Dialogue from "@/components/Dialogue";
import DataDialogue from "@/components/Dialogue/DataDialogue";
import GeneralInput from "@/components/GeneralInput";
import ActionView from "@/components/ActionView";
import { RESULT_TYPES } from "@/utils/constants";
import { useMemoizedFn } from "ahooks";
import classNames from "classnames";
import Logo from "../Logo";
import { Modal } from "antd";

type Props = {
  inputInfo: CHAT.TInputInfo;
  product?: CHAT.Product;
};

const ChatView: GenieType.FC<Props> = (props) => {
  const { inputInfo: inputInfoProp, product } = props;

  const [chatTitle, setChatTitle] = useState("");
  const [taskList, setTaskList] = useState<MESSAGE.Task[]>([]);
  const chatList = useRef<CHAT.ChatItem[]>([]);
  const [chatListState, setChatListState] = useState<CHAT.ChatItem[]>([]); // 添加状态用于触发重新渲染
  const [dataChatList, setDataChatList] = useState<Record<string, any>[]>([]);
  const [activeTask, setActiveTask] = useState<CHAT.Task>();
  const [plan, setPlan] = useState<CHAT.Plan>();
  const [showAction, setShowAction] = useState(false);
  const [loading, setLoading] = useState(false);
  const chatRef = useRef<HTMLInputElement>(null);
  const actionViewRef = ActionView.useActionView();
  const sessionId = useMemo(() => getSessionId(), []);
  const [modal, contextHolder] = Modal.useModal();

  const combineCurrentChat = (
    inputInfo: CHAT.TInputInfo,
    sessionId: string,
    requestId: string
  ): CHAT.ChatItem => {
    return {
      query: inputInfo.message!,
      files: inputInfo.files!,
      responseType: "txt",
      sessionId,
      requestId,
      loading: true,
      forceStop: false,
      tasks: [],
      thought: "",
      response: "",
      taskStatus: 0,
      tip: "已接收到你的任务，将立即开始处理...",
      multiAgent: { tasks: [] },
    };
  };

  const sendMessage = useMemoizedFn((inputInfo: CHAT.TInputInfo) => {
    console.log("[DEBUG] ========== sendMessage called ==========");
    const { message, deepThink, outputStyle } = inputInfo;
    const requestId = getUniqId();
    let currentChat = combineCurrentChat(inputInfo, sessionId, requestId);
    chatList.current = [...chatList.current, currentChat];
    setChatListState([...chatList.current]); // 触发重新渲染
    if (!chatTitle) {
      setChatTitle(message!);
    }
    setLoading(true);
    const params = {
      query: message,
      session_id: sessionId,
      request_id: requestId,
      model: "qwen-plus", // 可以根据需要选择模型
    };
    const handleMessage = (data: any) => {
      try {
        // 适配我们的后端响应格式
        console.log("[DEBUG] ========== handleMessage called in sendMessage ==========");
        console.log("[DEBUG] Received SSE message in sendMessage:", data);
        console.log("[DEBUG] Current chatList length:", chatList.current.length);
        console.log("[DEBUG] currentChat object:", currentChat);
        
        if (!data) {
          console.error("[ERROR] handleMessage received null or undefined data");
          return;
        }
        
        const { type, message: responseMessage, finished } = data; // 重命名避免冲突
        console.log("[DEBUG] Parsed values:", { type, responseMessage, finished });
        
        if (type === "error") {
        console.log("[DEBUG] Error message received:", responseMessage);
        currentChat.loading = false;
        currentChat.response = responseMessage || "处理请求时出错";
        setLoading(false);
        const newChatList = [...chatList.current];
        newChatList.splice(newChatList.length - 1, 1, currentChat);
        chatList.current = newChatList;
        setChatListState([...newChatList]); // 触发重新渲染
        scrollToTop(chatRef.current!);
        return;
      }
      
      if (type === "start") {
        // 初始消息，更新 tip
        console.log("[DEBUG] Start message:", responseMessage);
        currentChat.tip = responseMessage || "已接收到你的任务，将立即开始处理...";
        currentChat.loading = true;
        const newChatList = [...chatList.current];
        newChatList.splice(newChatList.length - 1, 1, currentChat);
        chatList.current = newChatList;
        setChatListState([...newChatList]); // 触发重新渲染
        scrollToTop(chatRef.current!);
      } else if (type === "response") {
        console.log("[DEBUG] Response message:", { responseMessage, finished, messageLength: responseMessage?.length });
        // 收到响应时，清除 tip，显示 response
        if (responseMessage !== undefined) {
          currentChat.response = responseMessage || "";
          currentChat.tip = ""; // 清除 tip，只显示 response
          currentChat.loading = !finished;
          if (finished) {
            console.log("[DEBUG] Message finished, stopping loading");
            setLoading(false);
          }
          const newChatList = [...chatList.current];
          newChatList.splice(newChatList.length - 1, 1, currentChat);
          chatList.current = newChatList;
          setChatListState([...newChatList]); // 触发重新渲染
          console.log("[DEBUG] Updated chat list, response:", currentChat.response);
          console.log("[DEBUG] Chat object:", JSON.stringify(currentChat, null, 2));
        }
        scrollToTop(chatRef.current!);
      } else {
        console.log("[DEBUG] Unknown message type:", type);
      }
      } catch (error) {
        console.error("[ERROR] Error in handleMessage:", error);
        console.error("[ERROR] Error stack:", (error as Error).stack);
        console.error("[ERROR] Data that caused error:", data);
      }
    };

    const openAction = (taskList: MESSAGE.Task[]) => {
      if (
        taskList.filter((t) => !RESULT_TYPES.includes(t.messageType)).length
      ) {
        setShowAction(true);
      }
    };

    const handleError = (error: unknown) => {
      throw error;
    };

    const handleClose = () => {
      console.log("🚀 ~ close");
    };

    querySSE(
      {
        body: params,
        handleMessage,
        handleError,
        handleClose,
      },
      `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/chat/query`
    );
  });

  const temporaryChangeTask = (taskList: MESSAGE.Task[]) => {
    const task = taskList[taskList.length - 1] as CHAT.Task;
    if (!["task_summary", "result"].includes(task?.messageType)) {
      setActiveTask(task);
    }
  };

  const changeTask = (task: CHAT.Task) => {
    actionViewRef.current?.changeActionView(ActionViewItemEnum.follow);
    changeActionStatus(true);
    setActiveTask(task);
  };

  const updatePlan = (plan: CHAT.Plan) => {
    setPlan(plan);
  };

  const changeFile = (file: CHAT.TFile) => {
    changeActionStatus(true);
    actionViewRef.current?.setFilePreview(file);
  };

  const changePlan = () => {
    changeActionStatus(true);
    actionViewRef.current?.openPlanView();
  };

  const changeActionStatus = (status: boolean) => {
    setShowAction(status);
  };

  const sendDataMessage = (inputInfo: any) => {
    console.log("[DEBUG] ========== sendDataMessage called ==========");
    const requestId = getUniqId();
    const params = {
      query: inputInfo.message,
      session_id: sessionId,
      request_id: requestId,
      model: "qwen-plus",
    };
    const currentChat = {
      query: inputInfo.message,
      loading: true,
      think: "",
      chartData: undefined,
      error: "",
    };
    setDataChatList([...dataChatList, currentChat]);
    scrollToTop(chatRef.current!);

    setChatTitle(inputInfo.message);
    setLoading(true);

    const handleMessage = (data: any) => {
      try {
        console.log("[DEBUG] ========== handleMessage called in sendDataMessage ==========");
        console.log("[DEBUG] Received SSE message in sendDataMessage:", data);
        // 适配我们的后端响应格式
        const { type, message, finished } = data;
        console.log("[DEBUG] Parsed values in sendDataMessage:", { type, message, finished });
        
        if (type === "error") {
          console.log("[DEBUG] Error message in sendDataMessage:", message);
          currentChat.error = message || "处理请求时出错";
          currentChat.loading = false;
          setLoading(false);
        } else if (type === "start") {
          console.log("[DEBUG] Start message in sendDataMessage:", message);
          currentChat.think = message || "正在处理...";
        } else if (type === "response") {
          console.log("[DEBUG] Response message in sendDataMessage:", { message, finished });
          // 尝试解析消息中的图表数据
          try {
            // 检查是否包含 JSON 代码块（Highcharts 配置）
            const jsonMatch = message.match(/```json\n([\s\S]*?)\n```/);
            if (jsonMatch) {
              currentChat.chartData = JSON.parse(jsonMatch[1]);
            }
            currentChat.response = message;
          } catch (e) {
            currentChat.response = message;
          }
          if (finished) {
            console.log("[DEBUG] Message finished in sendDataMessage");
            currentChat.loading = false;
            setLoading(false);
          }
        }
        const newChatList = [...dataChatList];
        // 修复：应该更新最后一个元素，而不是在末尾插入
        if (newChatList.length > 0) {
          newChatList[newChatList.length - 1] = currentChat;
        } else {
          newChatList.push(currentChat);
        }
        setDataChatList(newChatList);
        console.log("[DEBUG] Updated dataChatList, response:", currentChat.response);
        console.log("[DEBUG] dataChatList length:", newChatList.length);
        console.log("[DEBUG] Last chat in list:", newChatList[newChatList.length - 1]);
        // 滚动到顶部
        scrollToTop(chatRef.current!);
      } catch (error) {
        console.error("[ERROR] Error in sendDataMessage handleMessage:", error);
        console.error("[ERROR] Error stack:", (error as Error).stack);
        console.error("[ERROR] Data that caused error:", data);
      }
    };
    const handleError = (error: unknown) => {
      throw error;
    };

    const handleClose = () => {
      console.log("🚀 ~ close");
    };
    querySSE(
      {
        body: params,
        handleMessage,
        handleError,
        handleClose,
      },
      `${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'}/api/chat/query`
    );
  };

  useEffect(() => {
    if (inputInfoProp.message?.length !== 0) {
      product?.type === "dataAgent" && !inputInfoProp.deepThink
        ? sendDataMessage(inputInfoProp)
        : sendMessage(inputInfoProp);
    }
  }, [inputInfoProp, sendMessage]);

  const renderMultAgent = () => {
    return (
      <div className="h-full w-full flex justify-center">
        <div
          className={classNames("p-24 flex flex-col flex-1 w-0", {
            "max-w-[1200px]": !showAction,
          })}
          id="chat-view"
        >
          <div className="w-full flex justify-between">
            <div className="w-full flex items-center pb-8">
              <Logo />
              <div className="overflow-hidden whitespace-nowrap text-ellipsis text-[16px] font-[500] text-[#27272A] mr-8">
                {chatTitle}
              </div>
              {inputInfoProp.deepThink && (
                <div className="rounded-[4px] px-6 border-1 border-solid border-gray-300 flex items-center shrink-0">
                  <i className="font_family icon-shendusikao mr-6 text-[12px]"></i>
                  <span className="ml-[-4px]">深度研究</span>
                </div>
              )}
            </div>
          </div>
          <div
            className="w-full flex-1 overflow-auto no-scrollbar mb-[36px]"
            ref={chatRef}
          >
            {chatListState.map((chat) => {
              return (
                <div key={chat.requestId}>
                  <Dialogue
                    chat={chat}
                    deepThink={inputInfoProp.deepThink}
                    changeTask={changeTask}
                    changeFile={changeFile}
                    changePlan={changePlan}
                  />
                </div>
              );
            })}
          </div>
          <GeneralInput
            placeholder={
              loading ? "任务进行中" : "希望 Genie 为你做哪些任务呢？"
            }
            showBtn={false}
            size="medium"
            disabled={loading}
            product={product}
            // 多轮问答也不支持切换deepThink，使用传进来的
            send={(info) =>
              sendMessage({
                ...info,
                deepThink: inputInfoProp.deepThink,
              })
            }
          />
        </div>
        {contextHolder}
        <div
          className={classNames("transition-all w-0", {
            "opacity-0 overflow-hidden": !showAction,
            "flex-1": showAction,
          })}
        >
          <ActionView
            activeTask={activeTask}
            taskList={taskList}
            plan={plan}
            ref={actionViewRef}
            onClose={() => changeActionStatus(false)}
          />
        </div>
      </div>
    );
  };

  const renderDataAgent = () => {
    return (
      <div
        className={classNames("p-24 flex flex-col flex-1 w-0 max-w-[1200px]")}
      >
        <div className="w-full flex justify-between">
          <div className="w-full flex items-center pb-8">
            <Logo />
            <div className="overflow-hidden whitespace-nowrap text-ellipsis text-[16px] font-[500] text-[#27272A] mr-8">
              {chatTitle}
            </div>
          </div>
        </div>
        <div
          className="w-full flex-1 overflow-auto no-scrollbar mb-[36px]"
          ref={chatRef}
        >
          {dataChatList.map((chat, index) => {
            return (
              <div key={index}>
                <DataDialogue chat={chat} />
              </div>
            );
          })}
        </div>
        <GeneralInput
          placeholder={loading ? "任务进行中" : "希望 Genie 为你做哪些任务呢？"}
          showBtn={false}
          size="medium"
          disabled={loading}
          product={product}
          send={(info) =>
            sendDataMessage({
              ...info,
            })
          }
        />
      </div>
    );
  };

  return (
    <div className="h-full w-full flex justify-center">
      {product?.type === "dataAgent" && !inputInfoProp.deepThink
        ? renderDataAgent()
        : renderMultAgent()}
    </div>
  );
};

export default ChatView;
