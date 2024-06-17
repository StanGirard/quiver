import { AiOutlineLoading3Quarters } from "react-icons/ai";
import { BiCoin } from "react-icons/bi";
import {
  BsArrowRightShort,
  BsChatLeftText,
  BsTextParagraph,
} from "react-icons/bs";
import { CgSoftwareDownload } from "react-icons/cg";
import { CiFlag1 } from "react-icons/ci";
import {
  FaCalendar,
  FaCheck,
  FaCheckCircle,
  FaDiscord,
  FaFileAlt,
  FaFolder,
  FaGithub,
  FaKey,
  FaLinkedin,
  FaQuestionCircle,
  FaRegFileAlt,
  FaRegKeyboard,
  FaRegStar,
  FaRegThumbsDown,
  FaRegThumbsUp,
  FaRegUserCircle,
  FaTwitter,
  FaUnlock,
} from "react-icons/fa";
import { FaInfo } from "react-icons/fa6";
import { FiUpload } from "react-icons/fi";
import { GoLightBulb } from "react-icons/go";
import { GrResources } from "react-icons/gr";
import { HiBuildingOffice } from "react-icons/hi2";
import {
  IoIosAdd,
  IoIosHelpCircleOutline,
  IoIosNotifications,
  IoIosRadio,
  IoMdClose,
  IoMdLogOut,
  IoMdSettings,
  IoMdSync,
} from "react-icons/io";
import {
  IoArrowUpCircleOutline,
  IoCloudDownloadOutline,
  IoFootsteps,
  IoHomeOutline,
  IoShareSocial,
  IoWarningOutline,
} from "react-icons/io5";
import { LiaRobotSolid } from "react-icons/lia";
import { IconType } from "react-icons/lib";
import {
  LuBrain,
  LuBrainCircuit,
  LuChevronDown,
  LuChevronLeft,
  LuChevronRight,
  LuCopy,
  LuGoal,
  LuPlusCircle,
  LuSearch,
} from "react-icons/lu";
import {
  MdAlternateEmail,
  MdDarkMode,
  MdDashboardCustomize,
  MdDeleteOutline,
  MdDynamicFeed,
  MdHistory,
  MdLink,
  MdMarkEmailRead,
  MdMarkEmailUnread,
  MdOutlineLightMode,
  MdOutlineModeEditOutline,
  MdUnfoldLess,
  MdUnfoldMore,
  MdUploadFile,
} from "react-icons/md";
import { PiOfficeChairFill } from "react-icons/pi";
import { RiDeleteBackLine, RiHashtag } from "react-icons/ri";
import { SlOptions } from "react-icons/sl";
import { TbNetwork, TbRobot } from "react-icons/tb";
import { VscGraph } from "react-icons/vsc";

export const iconList: { [name: string]: IconType } = {
  add: LuPlusCircle,
  addWithoutCircle: IoIosAdd,
  assistant: TbRobot,
  back: RiDeleteBackLine,
  brain: LuBrain,
  brainCircuit: LuBrainCircuit,
  calendar: FaCalendar,
  chair: PiOfficeChairFill,
  chat: BsChatLeftText,
  check: FaCheck,
  checkCircle: FaCheckCircle,
  chevronDown: LuChevronDown,
  chevronLeft: LuChevronLeft,
  chevronRight: LuChevronRight,
  close: IoMdClose,
  coin: BiCoin,
  copy: LuCopy,
  custom: MdDashboardCustomize,
  delete: MdDeleteOutline,
  discord: FaDiscord,
  download: IoCloudDownloadOutline,
  edit: MdOutlineModeEditOutline,
  email: MdAlternateEmail,
  eureka: GoLightBulb,
  feed: MdDynamicFeed,
  file: FaRegFileAlt,
  fileSelected: FaFileAlt,
  flag: CiFlag1,
  fold: MdUnfoldLess,
  folder: FaFolder,
  followUp: IoArrowUpCircleOutline,
  github: FaGithub,
  goal: LuGoal,
  graph: VscGraph,
  hashtag: RiHashtag,
  help: IoIosHelpCircleOutline,
  history: MdHistory,
  home: IoHomeOutline,
  info: FaInfo,
  key: FaKey,
  link: MdLink,
  linkedin: FaLinkedin,
  loader: AiOutlineLoading3Quarters,
  logout: IoMdLogOut,
  moon: MdDarkMode,
  notifications: IoIosNotifications,
  office: HiBuildingOffice,
  options: SlOptions,
  paragraph: BsTextParagraph,
  prompt: FaRegKeyboard,
  question: FaQuestionCircle,
  redirection: BsArrowRightShort,
  radio: IoIosRadio,
  read: MdMarkEmailRead,
  robot: LiaRobotSolid,
  search: LuSearch,
  settings: IoMdSettings,
  share: IoShareSocial,
  software: CgSoftwareDownload,
  source: GrResources,
  star: FaRegStar,
  step: IoFootsteps,
  sun: MdOutlineLightMode,
  sync: IoMdSync,
  thumbsDown: FaRegThumbsDown,
  thumbsUp: FaRegThumbsUp,
  twitter: FaTwitter,
  unfold: MdUnfoldMore,
  unlock: FaUnlock,
  unread: MdMarkEmailUnread,
  upload: FiUpload,
  uploadFile: MdUploadFile,
  user: FaRegUserCircle,
  warning: IoWarningOutline,
  website: TbNetwork,
};
