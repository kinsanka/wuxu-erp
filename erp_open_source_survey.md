# 开源 ERP 调研与制造、医疗原型选型

调查日期 2026-11-20（北京时间）

## 检索范围

以 Linux Foundation LFX ERP 项目集合、GitHub 的 ERP 和 Open Source ERP 主题、制造 MRP 目录和 Gitee 中文检索为入口，沿官方仓库、许可证、部署文档和业务手册核对。纳入可公开定位的通用 ERP、制造 ERP、适合作为对照的轻量 ERP，以及医院、实验室和医疗供应链相关开源组件。分支、改名和不同版本合并在同一行。公开项目持续变化，目录、私有仓库和地区项目的能见度不同，无法证明全球穷尽。

- [Linux Foundation LFX ERP 项目集合](https://insights.linuxfoundation.org/collection/details/open-source-erp-suites)
- [GitHub ERP 主题](https://github.com/topics/erp)
- [GitHub Open Source ERP 主题](https://github.com/topics/open-source-erp)
- [制造 MRP 候选目录](https://mrpdirectory.com/open-source-mrp)
- [Gitee ERP 检索入口](https://gitee.com/explore/all?name=erp)

表中“—”表示本次未确认项目维护方提供可用的官方容器方案，第三方镜像不据此推断成熟度。许可证以所安装版本的 LICENSE 和模块声明为准。功能依据公开资料核对，未逐套安装试用。

## 一、通用、制造及轻量 ERP（26 项）

| 项目 | 许可证或版本边界 | 制造与供应链观察 | 部署入口或限制 |
|---|---|---|---|
| [ERPNext](https://github.com/frappe/erpnext) | GPL-3.0 | BOM、工单、工序、生产计划、批次、质检与会计，适合作为整套业务底座 | [Frappe Docker](https://github.com/frappe/frappe_docker)，医疗扩展用自定义镜像 |
| [Odoo Community](https://github.com/odoo/odoo) | LGPL-3.0；Enterprise 单独授权 | 基础 MRP、采购、库存，扩展看 [OCA/manufacture](https://github.com/OCA/manufacture)，高级质量与车间能力需逐版本查版别 | [官方镜像源](https://github.com/odoo/docker)，PostgreSQL |
| [Carbon CE](https://github.com/crbnos/carbon) | [AGPL-3.0，CE 与商业 EE 分开](https://docs.carbon.ms/docs/platform/licensing) | ERP、MES、QMS、生产计划、车间执行、批次/序列号，是制造专用界面对照 | [官方自托管教程](https://docs.carbon.ms/docs/platform/self-hosting)，PostgreSQL/Supabase 一类依赖 |
| [Tryton](https://www.tryton.org/) | GPL-3.0 系 | 模块化库存和批次，[生产模块](https://github.com/tryton/production)可组合；与 GNU Health 有同生态关联 | [部署与镜像入口](https://www.tryton.org/download)，PostgreSQL |
| [Axelor Open Suite](https://github.com/axelor/axelor-open-suite) | AGPL-3.0 | Java ERP、生产与供应链，适合研究工作流和对象扩展 | [官方安装入口](https://axelor.com/downloads/) |
| [iDempiere](https://github.com/idempiere/idempiere) | GPL-2.0 系 | 库存、供应链、制造、财务与应用字典，BOM/MRP 深度按发行版和插件核对 | [官方容器](https://github.com/idempiere/idempiere-docker) |
| [ADempiere](https://github.com/adempiere/adempiere) | GPL-2.0 系 | Compiere 系，适合对照 Libero 制造、BOM 与 MRP | 仓库部署文档；模块版本需单独核对 |
| [metasfresh](https://github.com/metasfresh/metasfresh) | GPL-2.0 系 | 强调分销和生产，有订单、仓储、制造与计划 | [官方 Docker 文档](https://docs.metasfresh.org/installation_collection/EN/How_do_I_setup_the_metasfresh_stack_using_Docker.html) |
| [Apache OFBiz](https://github.com/apache/ofbiz-framework) | Apache-2.0 | ERP 框架与应用，库存、采购、财务和 MRP；面向有实施开发团队 | [官方容器包](https://github.com/apache/ofbiz-framework/pkgs/container/ofbiz) |
| [Dolibarr](https://github.com/Dolibarr/dolibarr) | GPL-3.0 或更新 | 采购、销售、仓储及基础制造订单，适合轻量业务 | [项目 Docker 仓库](https://github.com/Dolibarr/dolibarr-docker) |
| [ERP5](https://lab.nexedi.com/nexedi/erp5) | GPL 系，按组件文件核对 | 通用 ERP 和工作流，适合研究单据与业务对象模型 | [部署生态 SlapOS](https://slapos.nexedi.com/) |
| [inoERP](https://github.com/inoerp/inoERP) | 按版本和仓库 LICENSE 核对 | 采购、库存、生产及计划；当前公开主仓为 Go/Flutter | [官网手册](https://docs.inoerp.com/docs/intro/) |
| [BlueSeer](https://github.com/blueseerERP/blueseer) | MIT | 离散制造与 EDI，适合研究汽车供应链交付单据 | 以 Java 客户端和项目分发为主 |
| [Kieselstein ERP](https://docs.kieselstein-erp.org/) | [核心及组件授权见官方说明](https://docs.kieselstein-erp.org/docs/einleitung/lizenzen/) | 中小制造、物料与工单，德语生态 | [项目源代码](https://gitlab.com/kieselstein-erp/sources) |
| [MyCompany](https://github.com/lsfusion-solutions/mycompany) | 程序 Apache-2.0；lsFusion 平台 LGPL-3.0 | 库存、采购销售、制造、项目、人事及门店 | [项目镜像](https://hub.docker.com/r/lsfusion/mycompany) |
| [Onfinity（原 VIENNA Advantage）](https://github.com/VIENNA-Advantage-ERP-CRM/Official-VAStandard-ERP-CRM) | 仓库说明为 Eclipse Public License；按发行包确认 | 采购、库存、财务与应用字典；制造社区功能按包确认 | [项目容器仓库](https://github.com/VIENNA-Advantage-ERP-CRM/OnfinityContainer) |
| [SCIPIO ERP](https://github.com/ilscipio/scipio-erp) | [4.0 起 AGPL-3.0 或商业许可；旧版 Apache-2.0](https://www.scipioerp.com/license/) | OFBiz 衍生，侧重电商和多渠道业务 | [项目下载入口](https://www.scipioerp.com/community/download/) |
| [Moqui / HiveMind](https://moqui.org/applications) | 按框架与应用仓库分别核对，Moqui 核心为 CC0 | 业务应用框架及组件，订单、履约、项目；实施时核对制造覆盖 | [项目镜像](https://hub.docker.com/u/moqui) |
| [OpenZ](https://github.com/openzsoftware/openz) | 查看仓库与社区发行包条款 | 德语 ERP，库存和制造候选 | — |
| [Kivitendo](https://github.com/kivitendo/kivitendo-erp) | GPL 系 | 德语 ERP、库存与财务，适合研究轻量订单交付 | — |
| [OpenConcerto](https://www.openconcerto.org/) | GPL 系 | 法语 ERP、会计与销售，适合作为轻量 ERP 对照 | — |
| [webERP](https://www.weberp.org/) | GPL 系 | 财务、库存、采购销售与基础生产 | 项目源代码与传统 Web 部署 |
| [FrontAccounting](https://frontaccounting.com/fawiki/index.php?n=Main.License) | GPL-3.0 或更新 | 会计、采购销售、库存、简单生产 | — |
| [LedgerSMB](https://ledgersmb.org/) | GPL 系 | 会计优先，适合对照会计和订单流程 | [项目 Docker 仓库](https://github.com/ledgersmb/ledgersmb-docker) |
| [FacturaScripts](https://github.com/NeoRazorX/facturascripts) | LGPL 系；插件另核 | 发票、会计、采购和库存，偏小企业 | — |
| [WP ERP](https://github.com/wp-erp/wp-erp) | GPL 系 | WordPress 上的 CRM、人事与会计，作为轻量对照 | 基于 WordPress 环境 |

## 二、中文 ERP 和进销存补充（5 项）

| 项目 | 公开边界 | 参考价值 |
|---|---|---|
| [管伊佳 ERP（jshERP）](https://github.com/jishenghua/jshERP) | Apache-2.0；当前仓库功能以公开代码为准 | 中文采购销售、调拨、组装拆卸、库存与权限 |
| [星云 ERP](https://github.com/lframework/xingyun) | Apache-2.0；主仓为后端，前端按 README 查对应仓 | 采购、库存、仓库、盘点、结算 |
| [芋道 ERP（RuoYi-Vue-Pro）](https://github.com/YunaiV/ruoyi-vue-pro) | 主仓 MIT，ERP 为独立业务模块 | 中文采购销售、仓储及权限结构，制造需单查 MES 模块及版本 |
| [启航电商 ERP](https://github.com/zeasin/qihang-erp-open) | [公开版 AGPL-3.0](https://qihangerp.cn/products/qihang-open/erp.html) | 面向多平台、多店铺订单与售后，对照渠道履约 |
| [启航零售 ERP](https://qihangerp.cn/products/open/retail-erp.html) | 官方公开版页面列 AGPL-3.0 | POS、门店、商品、零售库存，与电商 ERP 的产品范围不同 |

## 三、医疗信息与垂直组件（10 项）

| 项目 | 领域 | 如何参考 |
|---|---|---|
| [Marley Healthcare](https://github.com/earthians/marley) | Frappe/ERPNext 生态的医疗信息应用 | 门诊、住院、排班及临床业务结构；与 ERPNext 配套需按主版本构建镜像 |
| [Bahmni](https://www.bahmni.org/) | 医院信息系统集成套件 | 研究 OpenMRS、检验、ERP 的系统边界；标准版组件及许可证见[官方说明](https://www.bahmni.org/license)及[Docker 文档](https://bahmni.atlassian.net/wiki/spaces/BAH/pages/3117744129/Getting%20Started%20Quickly%20with%20Bahmni%20on%20Docker) |
| [GNU Health](https://docs.gnuhealth.org/his/appendix/faq.html) | Tryton 生态 HIS | 参考医疗数据模型与权限隔离 |
| [OpenMRS](https://github.com/openmrs/openmrs-core) | 临床记录平台 | 对照病历系统接口边界 |
| [OpenEMR](https://github.com/openemr/openemr) | EHR 和诊所运营 | 对照门诊流程与账单边界；有官方 Docker 工具 |
| [OpenBoxes](https://github.com/openboxes/openboxes) | 医疗供应链 WMS，EPL-1.0 | 医疗仓储与调拨、批号和效期、[库存管理](https://openboxes.cloud/docs/openboxes-guide/inventory)，是医疗物资工作流主要对照 |
| [OpenLMIS](https://github.com/OpenLMIS) | 医药物流信息系统 | 补货申请、库存可视化、公共卫生供应链；[授权说明](https://openlmis.org/tools/license/) |
| [Open mSupply](https://github.com/msupply-foundation/open-msupply) | 医药供应链 LMIS | 医疗配送、调拨与补货；许可证是 mSupply 自定义条款，单独审阅，未计入通用开源 ERP |
| [OpenELIS Global](https://github.com/openelisglobal) | LIS | 对照检验系统接口与功能边界 |
| [SENAITE](https://github.com/senaite/senaite.core) | LIMS | 对照样品、检验流程与结果发布 |

## 四、相邻与历史项目（7 项）

| 项目 | 核对结论 |
|---|---|
| [InvenTree](https://github.com/inventree/InvenTree) | 面向物料、BOM、库存和生产装配的开源工具，适合做离散制造执行对照 |
| [PartKeepr](https://github.com/partkeepr/PartKeepr) | 电子元件库存，仓库已归档，适合历史参考 |
| [Compiere](https://sourceforge.net/projects/compiere/) | 历史社区版线索，商业支持、当前可得源码及部署需逐案核实 |
| [Openbravo ERP](https://sourceforge.net/projects/openbravo/) | 历史社区版线索，和当前商业产品区分 |
| [xTuple PostBooks](https://sourceforge.net/projects/postbooks/) | 历史开源发行线索，和当前 xTuple 商业产品区分 |
| [Akaunting](https://github.com/akaunting/akaunting) | 主要为会计工具；当前主仓涉及 BSL 条款，按源码可见项目处理 |
| [GenisourceERP](https://github.com/GenisourceStudio/GenisourceERP) | 中文制造关键词候选；本次未确认公开许可证、完整模块和持续部署条件 |

## 五、优先深入验证的方案

| 目标 | 优先候选 | 安装验证时要看 |
|---|---|---|
| 从成熟 ERP 快速导入工厂业务 | ERPNext | 同一工单的 BOM 版本、缺料、实耗批次、检验及成本是否可连续追踪 |
| 面向离散制造做车间、质量一体化 | Carbon CE；Odoo Community + OCA | 看板、设备工序、领料、序列追踪，以及 CE/EE 或插件的实际边界 |
| 从医院二级库与 SPD 切入 | OpenBoxes + 成熟 ERP，或 ERPNext + 专项扩展 | 一级库到二级库、批号/效期、一物一码、术中耗用、费用回执和召回 |
| 还需要门诊住院和临床记录 | ERPNext + Marley；Bahmni；GNU Health | ERP 与 HIS 接口、身份映射、权限、医疗本地化，逐模块检查 |
| 面向复杂组织、集团财务和重度集成 | iDempiere；Apache OFBiz；Axelor | 组织隔离、账务、价格和审批的配置成本，以及升级与维护 |

## 六、依据调研确定的制作范围

独立编写中文源代码，便于先验证工作流和数据模型。参考 ERPNext 的工单与质检、Carbon 的制造追溯组织、OpenBoxes 的批次调拨，以及 GS1 的基础标识字段。合并到同一库存事件模型，一件材料或耗材在收货时拥有批次，后续流向用事件关联。

| 工作流 | 首版实现 | 后续需要真实业务数据与接口 |
|---|---|---|
| 采购到入库 | 供应商、采购单、审核、部分收货、批次效期、隔离与放行 | 合同、来料抽样规则、供应商绩效、应付和税票 |
| 销售到发货 | 客户、销售单、审核、部分发货、库存流水 | 报价、发票、收款、退货红冲 |
| 制造 | BOM 版本、工单、单阶净缺料、工序报工、按 FEFO 领用、完工待检、投入产出关联 | 多阶时段 MRP、工序排程、拆分完工、标准与实际成本核算、MES 对接 |
| 医院耗材 | 中心库、手术室二级库、包装码首次入库、扫码调拨和耗用、计费对账状态、批次冻结 | HIS/SPD 双向对接、寄售结算、灭菌状态、完整 UDI 规则、撤销与费用冲正 |
| 库存质量 | 批次放行、冻结、可用量与低库存、跨库移转、库存与审计导出 | 盘点差异审批、采购退货、全面召回通知与关闭 |

首版使用虚构批号、耗材码和病例业务号演示。病例号是耗材业务的关联字段。数据库允许部署在自有环境，真实系统接入需另外定义主数据、权限、回执与实施验收。

[GS1 标识字段说明](https://support.gs1.org/support/solutions/articles/43000757407-which-data-elements-application-identifiers-ai-should-must-be-used)
